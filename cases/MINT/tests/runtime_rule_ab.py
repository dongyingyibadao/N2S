#!/usr/bin/env python3
"""Run paired sinusoidal FP64 and torch.compile capability A/B checks."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
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
SINUSOIDAL_CASES = (
    {"dimension": 32, "min_period": 0.004, "max_period": 4.0},
    {"dimension": 256, "min_period": 0.004, "max_period": 4.0},
    {"dimension": 1024, "min_period": 0.0001, "max_period": 10000.0},
)


def exception_payload(exc: BaseException) -> dict[str, str]:
    return {
        "type": type(exc).__name__,
        "message": str(exc),
        "traceback_tail": "\n".join(traceback.format_exc().splitlines()[-10:]),
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

    def empty_cache(self) -> None:
        self.api.empty_cache()

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
            result.update(cuda_runtime=torch.version.cuda, cudnn=torch.backends.cudnn.version())
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


def base_test(test_id: str, classification: str, input_spec: dict) -> dict:
    return {
        "id": test_id,
        "classification": classification,
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
    test = base_test("runtime_rule_backend_availability", "device_library_replacement", {})
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


def sinusoidal(
    time_values: torch.Tensor,
    dimension: int,
    min_period: float,
    max_period: float,
    dtype: torch.dtype,
) -> torch.Tensor:
    fraction = torch.linspace(
        0.0,
        1.0,
        dimension // 2,
        dtype=dtype,
        device=time_values.device,
    )
    period = min_period * (max_period / min_period) ** fraction
    phase = (2 * math.pi / period)[None, :] * time_values.to(dtype=dtype)[:, None]
    return torch.cat([phase.sin(), phase.cos()], dim=1)


def measure_peak(callable_, backend: Backend) -> tuple[torch.Tensor, dict[str, int]]:
    backend.synchronize()
    starting = backend.memory_allocated()
    backend.reset_peak_memory()
    output = callable_()
    backend.synchronize()
    peak = backend.max_memory_allocated()
    return output, {
        "starting_allocated_bytes": starting,
        "peak_allocated_bytes": peak,
        "peak_increment_bytes": max(0, peak - starting),
    }


def paired_samples(baseline, candidate, backend: Backend, warmup: int, repeats: int):
    for _ in range(warmup):
        baseline()
        candidate()
        backend.synchronize()
    samples = {"baseline": [], "candidate": []}
    outputs = {}
    callables = {"baseline": baseline, "candidate": candidate}
    for repeat in range(repeats):
        order = ("baseline", "candidate") if repeat % 2 == 0 else ("candidate", "baseline")
        for variant in order:
            started = time.perf_counter()
            outputs[variant] = callables[variant]()
            backend.synchronize()
            samples[variant].append(time.perf_counter() - started)
    return outputs, samples


def sinusoidal_functional_ab(backend: Backend) -> dict:
    time_values = [0.0, 0.001, 0.01, 0.125, 0.5, 0.999, 1.0]
    test = base_test(
        "sinusoidal_fp64_functional_ab",
        "numerical_precision",
        {
            "time": time_values,
            "cases": list(SINUSOIDAL_CASES),
            "baseline": f"{backend.name.upper()} float64",
            "candidate": f"{backend.name.upper()} float32 fallback",
            "reference": "CPU float64",
        },
    )
    cpu_time = torch.tensor(time_values, dtype=torch.float64)
    device_time = cpu_time.to(backend.device)
    case_results = []
    candidate_all_passed = True
    baseline_all_passed = True
    for case in SINUSOIDAL_CASES:
        record = {"input": case, "baseline": {"status": "failed"}, "candidate": {"status": "failed"}}
        reference = sinusoidal(cpu_time, **case, dtype=torch.float64)
        baseline_output = None
        try:
            baseline_output = sinusoidal(device_time, **case, dtype=torch.float64)
            backend.synchronize()
            record["baseline"] = {
                "status": "passed",
                "output_dtype": str(baseline_output.dtype),
                "finite_output": bool(torch.isfinite(baseline_output).all().item()),
                "vs_cpu_fp64": numerical_metrics(reference, baseline_output),
            }
        except Exception as exc:
            baseline_all_passed = False
            record["baseline"]["exception"] = exception_payload(exc)
        try:
            candidate_output = sinusoidal(device_time.float(), **case, dtype=torch.float32)
            backend.synchronize()
            record["candidate"] = {
                "status": "passed",
                "output_dtype": str(candidate_output.dtype),
                "finite_output": bool(torch.isfinite(candidate_output).all().item()),
                "vs_cpu_fp64": numerical_metrics(reference, candidate_output),
            }
            if baseline_output is not None:
                record["candidate"]["vs_baseline"] = numerical_metrics(baseline_output, candidate_output)
        except Exception as exc:
            candidate_all_passed = False
            record["candidate"]["exception"] = exception_payload(exc)
        case_results.append(record)
    test["variants"] = {"cases": case_results}
    test["metrics"] = {
        "baseline_all_cases_passed": baseline_all_passed,
        "candidate_all_cases_passed": candidate_all_passed,
        "fallback_functionally_required_in_this_environment": not baseline_all_passed,
    }
    if candidate_all_passed:
        test["status"] = "passed"
        test["evidence_status"] = f"{backend.name}_passed"
    else:
        test["exception"] = next(
            case["candidate"].get("exception") for case in case_results if case["candidate"]["status"] == "failed"
        )
        test["evidence_status"] = f"{backend.name}_failed"
    return test


def sinusoidal_performance_ab(backend: Backend, warmup: int, repeats: int) -> dict:
    input_size = 4096
    dimension = 1024
    test = base_test(
        "sinusoidal_fp64_performance_ab",
        "numerical_precision",
        {
            "time_shape": [input_size],
            "dimension": dimension,
            "min_period": 0.004,
            "max_period": 4.0,
            "warmup": warmup,
            "repeats_per_variant": repeats,
            "timing_order": "alternating AB/BA",
            "baseline": f"{backend.name.upper()} float64",
            "candidate": f"{backend.name.upper()} float32 fallback",
        },
    )
    try:
        cpu_time = torch.linspace(0.0, 1.0, input_size, dtype=torch.float64)
        time_fp64 = cpu_time.to(backend.device)
        time_fp32 = time_fp64.float()

        def baseline():
            return sinusoidal(time_fp64, dimension, 0.004, 4.0, torch.float64)

        def candidate():
            return sinusoidal(time_fp32, dimension, 0.004, 4.0, torch.float32)

        outputs, samples = paired_samples(baseline, candidate, backend, warmup, repeats)
        baseline_cpu = outputs["baseline"].detach().cpu()
        candidate_cpu = outputs["candidate"].detach().cpu()
        del outputs
        backend.empty_cache()
        baseline_output, baseline_memory = measure_peak(baseline, backend)
        del baseline_output
        backend.empty_cache()
        candidate_output, candidate_memory = measure_peak(candidate, backend)
        del candidate_output
        backend.empty_cache()
        baseline_summary = sample_summary(samples["baseline"])
        candidate_summary = sample_summary(samples["candidate"])
        test["baseline_samples"] = samples["baseline"]
        test["samples"] = samples["candidate"]
        test["metrics"] = {
            "baseline": baseline_summary,
            "candidate": candidate_summary,
            "candidate_median_ratio": candidate_summary["median_seconds"] / baseline_summary["median_seconds"],
            "candidate_vs_baseline": numerical_metrics(baseline_cpu, candidate_cpu),
        }
        test["memory"] = {
            "baseline": baseline_memory,
            "candidate": candidate_memory,
            "candidate_minus_baseline_peak_increment_bytes": (
                candidate_memory["peak_increment_bytes"] - baseline_memory["peak_increment_bytes"]
            ),
        }
        test["variants"] = {
            "baseline": {"status": "passed", "samples": samples["baseline"]},
            "candidate": {"status": "passed", "samples": samples["candidate"]},
        }
        test["status"] = "passed"
        test["evidence_status"] = f"{backend.name}_passed"
    except Exception as exc:
        test["exception"] = exception_payload(exc)
        test["evidence_status"] = f"{backend.name}_failed"
    return test


def compile_capability_ab(backend: Backend, warmup: int, repeats: int) -> dict:
    test = base_test(
        "compile_capability_ab",
        "operator_implementation",
        {
            "shape": [128, 128],
            "dtype": "float32",
            "compile_mode": "max-autotune",
            "warmup": warmup,
            "repeats": repeats,
            "baseline": "torch.compile requested",
            "candidate": "observable eager fallback",
        },
    )
    generator = torch.Generator(device="cpu").manual_seed(SEED)
    fixed = torch.randn(128, 128, generator=generator, dtype=torch.float32).to(backend.device)

    def toy(value: torch.Tensor) -> torch.Tensor:
        return torch.tanh(value @ value.transpose(0, 1) / math.sqrt(value.shape[1])) + torch.sin(value)

    variants = {
        "baseline": {"status": "failed", "samples": [], "metrics": {}, "memory": {}, "exception": None},
        "candidate": {"status": "failed", "samples": [], "metrics": {}, "memory": {}, "exception": None},
    }
    compiled_output = None
    compiled = None
    try:
        create_started = time.perf_counter()
        compiled = torch.compile(toy, mode="max-autotune")
        variants["baseline"]["metrics"]["wrapper_creation_seconds"] = time.perf_counter() - create_started
        starting = backend.memory_allocated()
        backend.reset_peak_memory()
        first_started = time.perf_counter()
        compiled_output = compiled(fixed)
        backend.synchronize()
        variants["baseline"]["metrics"]["first_call_seconds"] = time.perf_counter() - first_started
        variants["baseline"]["memory"] = {
            "starting_allocated_bytes": starting,
            "peak_allocated_bytes": backend.max_memory_allocated(),
            "peak_increment_bytes": max(0, backend.max_memory_allocated() - starting),
        }
        for _ in range(warmup):
            compiled(fixed)
            backend.synchronize()
        samples = []
        for _ in range(repeats):
            started = time.perf_counter()
            compiled_output = compiled(fixed)
            backend.synchronize()
            samples.append(time.perf_counter() - started)
        variants["baseline"].update(status="passed", samples=samples)
        variants["baseline"]["metrics"].update(sample_summary(samples))
    except Exception as exc:
        try:
            backend.synchronize()
        except Exception:
            pass
        variants["baseline"]["metrics"]["time_to_exception_seconds"] = (
            time.perf_counter() - first_started if "first_started" in locals() else None
        )
        variants["baseline"]["exception"] = exception_payload(exc)
        if "starting" in locals():
            peak = backend.max_memory_allocated()
            variants["baseline"]["memory"] = {
                "starting_allocated_bytes": starting,
                "peak_allocated_bytes": peak,
                "peak_increment_bytes": max(0, peak - starting),
            }

    eager_output = None
    try:
        backend.empty_cache()
        starting = backend.memory_allocated()
        backend.reset_peak_memory()
        for _ in range(warmup):
            eager_output = toy(fixed)
            backend.synchronize()
        samples = []
        for _ in range(repeats):
            started = time.perf_counter()
            eager_output = toy(fixed)
            backend.synchronize()
            samples.append(time.perf_counter() - started)
        peak = backend.max_memory_allocated()
        variants["candidate"].update(
            status="passed",
            samples=samples,
            metrics={**sample_summary(samples), "finite_output": bool(torch.isfinite(eager_output).all().item())},
            memory={
                "starting_allocated_bytes": starting,
                "peak_allocated_bytes": peak,
                "peak_increment_bytes": max(0, peak - starting),
            },
        )
        if compiled_output is not None:
            variants["candidate"]["metrics"]["vs_compiled"] = numerical_metrics(compiled_output, eager_output)
    except Exception as exc:
        variants["candidate"]["exception"] = exception_payload(exc)

    test["variants"] = variants
    test["samples"] = variants["candidate"]["samples"]
    test["baseline_samples"] = variants["baseline"]["samples"]
    test["metrics"] = {
        "functional_outcome": (
            f"compile_{variants['baseline']['status']}_eager_{variants['candidate']['status']}"
        ),
        "compile_capability_available": variants["baseline"]["status"] == "passed",
        "triton_importable": importlib.util.find_spec("triton") is not None,
    }
    if variants["baseline"]["status"] == "passed" and variants["candidate"]["status"] == "passed":
        test["metrics"]["compiled_median_ratio_vs_eager"] = (
            variants["baseline"]["metrics"]["median_seconds"]
            / variants["candidate"]["metrics"]["median_seconds"]
        )
    test["memory"] = {name: variant["memory"] for name, variant in variants.items()}
    if variants["candidate"]["status"] == "passed":
        test["status"] = "passed"
        test["evidence_status"] = f"{backend.name}_passed"
    else:
        test["exception"] = variants["candidate"]["exception"]
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
    tests = [
        sinusoidal_functional_ab(backend),
        sinusoidal_performance_ab(backend, warmup, repeats),
        compile_capability_ab(backend, warmup, repeats),
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
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--repeats", type=int, default=20)
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
