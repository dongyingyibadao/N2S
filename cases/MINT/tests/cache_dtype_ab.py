#!/usr/bin/env python3
"""Run paired cache-dtype functional and overhead checks on one accelerator."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import platform
from pathlib import Path
import statistics
import sys
import time
import traceback

import torch
import torch.nn.functional as F


SEED = 42
ACCEPTANCE = "record_only_no_unified_threshold"
QKV_SHAPE = (2, 4, 16, 32)


def exception_payload(exc: BaseException) -> dict[str, str]:
    return {
        "type": type(exc).__name__,
        "message": str(exc),
        "traceback_tail": "\n".join(traceback.format_exc().splitlines()[-8:]),
    }


def numerical_metrics(reference: torch.Tensor, candidate: torch.Tensor) -> dict[str, float]:
    ref = reference.detach().cpu().double().reshape(-1)
    got = candidate.detach().cpu().double().reshape(-1)
    delta = got - ref
    return {
        "max_abs_error": delta.abs().max().item(),
        "max_relative_error": (delta.abs() / ref.abs().clamp_min(1e-12)).max().item(),
        "rmse": delta.square().mean().sqrt().item(),
        "cosine_similarity": F.cosine_similarity(ref[None, :], got[None, :]).item(),
    }


class Backend:
    def __init__(self, name: str, index: int):
        self.name = name
        self.index = index
        self.module_version = None
        if name == "npu":
            import torch_npu

            self.module_version = torch_npu.__version__
            self.api = torch.npu
        else:
            self.api = torch.cuda

    @property
    def device(self) -> torch.device:
        return torch.device(f"{self.name}:{self.index}")

    def available(self) -> bool:
        return bool(self.api.is_available())

    def activate(self) -> None:
        self.api.set_device(self.index)

    def synchronize(self) -> None:
        self.api.synchronize()

    def memory_allocated(self) -> int:
        return int(self.api.memory_allocated(self.index))

    def max_memory_allocated(self) -> int:
        return int(self.api.max_memory_allocated(self.index))

    def reset_peak_memory(self) -> None:
        self.api.reset_peak_memory_stats(self.index)

    def environment(self) -> dict:
        result = {
            "device": self.api.get_device_name(self.index),
            "device_index": self.index,
            "torch": torch.__version__,
            "python": platform.python_version(),
            "platform": platform.platform(),
        }
        if self.name == "npu":
            result["torch_npu"] = self.module_version
        else:
            result.update(
                cuda_runtime=torch.version.cuda,
                cudnn=torch.backends.cudnn.version(),
            )
        return result


def percentile95(samples: list[float]) -> float:
    return sorted(samples)[math.ceil(0.95 * len(samples)) - 1]


def sample_summary(samples: list[float]) -> dict[str, float | int]:
    return {
        "count": len(samples),
        "median_seconds": statistics.median(samples),
        "p95_seconds": percentile95(samples),
        "min_seconds": min(samples),
        "max_seconds": max(samples),
    }


def base_test(test_id: str, input_spec: dict) -> dict:
    return {
        "id": test_id,
        "classification": "numerical_precision",
        "status": "failed",
        "evidence_status": "static_analysis",
        "seed": SEED,
        "input": input_spec,
        "checkpoint": None,
        "samples": [],
        "metrics": {},
        "memory": {},
        "exception": None,
        "acceptance": ACCEPTANCE,
    }


def unavailable_result(backend: str, reason: str) -> dict:
    status = "pending_cuda" if backend == "cuda" else "failed"
    test = base_test("cache_dtype_backend_availability", {})
    test.update(
        status=status,
        evidence_status=status if backend == "cuda" else "npu_failed",
        exception={"type": "BackendUnavailable", "message": reason, "traceback_tail": ""},
    )
    return {
        "schema_version": "1.0.0",
        "case": "MINT",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "promotion_status": "exploratory",
        "backend": backend,
        "environment": {"torch": torch.__version__, "platform": platform.platform()},
        "tests": [test],
    }


def measure_peak_increment(callable_, backend: Backend) -> tuple[torch.Tensor, dict[str, int]]:
    backend.synchronize()
    before = backend.memory_allocated()
    backend.reset_peak_memory()
    output = callable_()
    backend.synchronize()
    peak = backend.max_memory_allocated()
    return output, {
        "starting_allocated_bytes": before,
        "peak_allocated_bytes": peak,
        "peak_increment_bytes": max(0, peak - before),
    }


def paired_samples(
    baseline,
    candidate,
    backend: Backend,
    warmup: int,
    repeats: int,
) -> tuple[torch.Tensor, torch.Tensor, list[float], list[float]]:
    baseline_output = None
    candidate_output = None
    for _ in range(warmup):
        baseline_output = baseline()
        candidate_output = candidate()
        backend.synchronize()

    samples = {"baseline": [], "candidate": []}
    callables = {"baseline": baseline, "candidate": candidate}
    outputs = {}
    # AB/BA ordering reduces monotonic clock and thermal bias without hiding raw samples.
    for repeat in range(repeats):
        order = ("baseline", "candidate") if repeat % 2 == 0 else ("candidate", "baseline")
        for variant in order:
            started = time.perf_counter()
            outputs[variant] = callables[variant]()
            backend.synchronize()
            samples[variant].append(time.perf_counter() - started)
    return outputs["baseline"], outputs["candidate"], samples["baseline"], samples["candidate"]


def functional_ab(
    q_cpu: torch.Tensor,
    k_cpu: torch.Tensor,
    v_cpu: torch.Tensor,
    backend: Backend,
) -> dict:
    test = base_test(
        "cache_dtype_functional_ab",
        {
            "qkv_shape": list(QKV_SHAPE),
            "baseline": "BF16 query with FP32 key/value",
            "candidate": "key/value locally cast to query dtype before SDPA",
            "reference": "CPU FP32 SDPA",
        },
    )
    q = q_cpu.to(device=backend.device, dtype=torch.bfloat16)
    k = k_cpu.to(device=backend.device, dtype=torch.float32)
    v = v_cpu.to(device=backend.device, dtype=torch.float32)
    variants = {
        "baseline": {"status": "failed", "output_dtype": None, "exception": None},
        "candidate": {"status": "failed", "output_dtype": None, "exception": None},
    }

    baseline_output = None
    try:
        baseline_output = F.scaled_dot_product_attention(q, k, v)
        backend.synchronize()
        variants["baseline"].update(
            status="passed",
            output_dtype=str(baseline_output.dtype),
            finite_output=bool(torch.isfinite(baseline_output).all().item()),
        )
    except Exception as exc:
        variants["baseline"]["exception"] = exception_payload(exc)

    candidate_output = None
    try:
        candidate_output, candidate_memory = measure_peak_increment(
            lambda: F.scaled_dot_product_attention(q, k.to(dtype=q.dtype), v.to(dtype=q.dtype)),
            backend,
        )
        variants["candidate"].update(
            status="passed",
            output_dtype=str(candidate_output.dtype),
            finite_output=bool(torch.isfinite(candidate_output).all().item()),
            memory=candidate_memory,
        )
        reference = F.scaled_dot_product_attention(q_cpu, k_cpu, v_cpu)
        test["metrics"]["candidate_vs_cpu_fp32"] = numerical_metrics(reference, candidate_output)
        if baseline_output is not None:
            test["metrics"]["candidate_vs_baseline"] = numerical_metrics(baseline_output, candidate_output)
        test["status"] = "passed"
        test["evidence_status"] = f"{backend.name}_passed"
    except Exception as exc:
        variants["candidate"]["exception"] = exception_payload(exc)
        test["exception"] = variants["candidate"]["exception"]
        test["evidence_status"] = f"{backend.name}_failed"

    test["metrics"]["baseline_behavior"] = (
        "mixed_dtype_accepted" if variants["baseline"]["status"] == "passed" else "mixed_dtype_rejected"
    )
    test["variants"] = variants
    return test


def overhead_ab(
    q_cpu: torch.Tensor,
    k_cpu: torch.Tensor,
    v_cpu: torch.Tensor,
    backend: Backend,
    warmup: int,
    repeats: int,
) -> dict:
    test = base_test(
        "cache_dtype_cast_overhead_ab",
        {
            "qkv_shape": list(QKV_SHAPE),
            "warmup": warmup,
            "repeats_per_variant": repeats,
            "timing_order": "alternating AB/BA",
            "baseline": "pre-aligned BF16 key/value, cast outside measured region",
            "candidate": "FP32 key/value cast to BF16 inside measured region",
            "scope": "isolates local cast cost; not a full-model performance threshold",
        },
    )
    try:
        q = q_cpu.to(device=backend.device, dtype=torch.bfloat16)
        k_source = k_cpu.to(device=backend.device, dtype=torch.float32)
        v_source = v_cpu.to(device=backend.device, dtype=torch.float32)
        k_aligned = k_source.to(dtype=q.dtype)
        v_aligned = v_source.to(dtype=q.dtype)

        def baseline():
            return F.scaled_dot_product_attention(q, k_aligned, v_aligned)

        def candidate():
            return F.scaled_dot_product_attention(
                q,
                k_source.to(dtype=q.dtype),
                v_source.to(dtype=q.dtype),
            )

        baseline_output, candidate_output, baseline_samples, candidate_samples = paired_samples(
            baseline, candidate, backend, warmup, repeats
        )
        _, baseline_memory = measure_peak_increment(baseline, backend)
        _, candidate_memory = measure_peak_increment(candidate, backend)
        baseline_summary = sample_summary(baseline_samples)
        candidate_summary = sample_summary(candidate_samples)
        test["samples"] = candidate_samples
        test["baseline_samples"] = baseline_samples
        test["metrics"] = {
            "baseline": baseline_summary,
            "candidate": candidate_summary,
            "candidate_vs_baseline": numerical_metrics(baseline_output, candidate_output),
            "candidate_median_ratio": (
                candidate_summary["median_seconds"] / baseline_summary["median_seconds"]
            ),
            "finite_outputs": bool(
                torch.isfinite(baseline_output).all().item()
                and torch.isfinite(candidate_output).all().item()
            ),
        }
        test["memory"] = {
            "baseline": baseline_memory,
            "candidate": candidate_memory,
            "candidate_minus_baseline_peak_increment_bytes": (
                candidate_memory["peak_increment_bytes"] - baseline_memory["peak_increment_bytes"]
            ),
        }
        test["variants"] = {
            "baseline": {"status": "passed", "samples": baseline_samples},
            "candidate": {"status": "passed", "samples": candidate_samples},
        }
        test["status"] = "passed"
        test["evidence_status"] = f"{backend.name}_passed"
    except Exception as exc:
        test["exception"] = exception_payload(exc)
        test["evidence_status"] = f"{backend.name}_failed"
    return test


def noop_control(q_cpu: torch.Tensor, k_cpu: torch.Tensor, v_cpu: torch.Tensor, backend: Backend) -> dict:
    test = base_test(
        "cache_dtype_already_aligned_control",
        {
            "qkv_shape": list(QKV_SHAPE),
            "input_dtype": "bfloat16",
            "candidate": "tensor.to(dtype=current_dtype)",
        },
    )
    try:
        q = q_cpu.to(device=backend.device, dtype=torch.bfloat16)
        k = k_cpu.to(device=backend.device, dtype=torch.bfloat16)
        v = v_cpu.to(device=backend.device, dtype=torch.bfloat16)
        cast_k = k.to(dtype=q.dtype)
        cast_v = v.to(dtype=q.dtype)
        baseline = F.scaled_dot_product_attention(q, k, v)
        candidate = F.scaled_dot_product_attention(q, cast_k, cast_v)
        backend.synchronize()
        test["metrics"] = {
            "key_storage_reused": k.data_ptr() == cast_k.data_ptr(),
            "value_storage_reused": v.data_ptr() == cast_v.data_ptr(),
            "candidate_vs_baseline": numerical_metrics(baseline, candidate),
        }
        test["status"] = "passed"
        test["evidence_status"] = f"{backend.name}_passed"
    except Exception as exc:
        test["exception"] = exception_payload(exc)
        test["evidence_status"] = f"{backend.name}_failed"
    return test


def run(backend_name: str, device_index: int, warmup: int, repeats: int) -> dict:
    try:
        backend = Backend(backend_name, device_index)
    except Exception as exc:
        return unavailable_result(backend_name, f"backend import failed: {exc}")
    if not backend.available():
        return unavailable_result(backend_name, f"torch.{backend_name}.is_available() is false")

    backend.activate()
    torch.manual_seed(SEED)
    generator = torch.Generator(device="cpu").manual_seed(SEED)
    q_cpu = torch.randn(*QKV_SHAPE, generator=generator, dtype=torch.float32)
    k_cpu = torch.randn(*QKV_SHAPE, generator=generator, dtype=torch.float32)
    v_cpu = torch.randn(*QKV_SHAPE, generator=generator, dtype=torch.float32)
    tests = [
        functional_ab(q_cpu, k_cpu, v_cpu, backend),
        overhead_ab(q_cpu, k_cpu, v_cpu, backend, warmup, repeats),
        noop_control(q_cpu, k_cpu, v_cpu, backend),
    ]
    return {
        "schema_version": "1.0.0",
        "case": "MINT",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "promotion_status": "exploratory",
        "backend": backend_name,
        "environment": backend.environment(),
        "tests": tests,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("npu", "cuda"), required=True)
    parser.add_argument("--device-index", type=int, default=0)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--repeats", type=int, default=50)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.device_index < 0 or args.warmup < 0 or args.repeats < 1:
        parser.error("device-index and warmup must be non-negative; repeats must be positive")

    result = run(args.backend, args.device_index, args.warmup, args.repeats)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if all(test["status"] in {"passed", "pending_cuda"} for test in result["tests"]) else 1


if __name__ == "__main__":
    sys.exit(main())
