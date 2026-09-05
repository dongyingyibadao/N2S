#!/usr/bin/env python3
"""Run fixed-input numerical checks without importing the full MINT model."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import platform
from pathlib import Path
import statistics
import time
import traceback

import torch
import torch.nn.functional as F


SEED = 42
ACCEPTANCE = "record_only_no_unified_threshold"


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


def synchronize(backend: str) -> None:
    if backend == "npu":
        torch.npu.synchronize()
    else:
        torch.cuda.synchronize()


def peak_memory(backend: str) -> int:
    if backend == "npu":
        return torch.npu.max_memory_allocated()
    return torch.cuda.max_memory_allocated()


def reset_peak_memory(backend: str) -> None:
    if backend == "npu":
        torch.npu.reset_peak_memory_stats()
    else:
        torch.cuda.reset_peak_memory_stats()


def timed(callable_, backend: str, warmup: int = 3, repeats: int = 10):
    output = None
    for _ in range(warmup):
        output = callable_()
        synchronize(backend)
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        output = callable_()
        synchronize(backend)
        samples.append(time.perf_counter() - started)
    return output, samples


def percentile95(samples: list[float]) -> float:
    return sorted(samples)[math.ceil(0.95 * len(samples)) - 1]


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


def pending_result(backend: str, reason: str) -> dict:
    test = base_test("backend_availability", "device_library_replacement", {})
    test.update(
        status="pending_cuda" if backend == "cuda" else "failed",
        evidence_status="pending_cuda" if backend == "cuda" else "npu_failed",
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("npu", "cuda"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    backend = args.backend
    backend_module_version = None
    if backend == "npu":
        try:
            import torch_npu  # noqa: F401

            backend_module_version = torch_npu.__version__
        except Exception as exc:
            result = pending_result(backend, f"torch_npu import failed: {exc}")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            return
        available = torch.npu.is_available()
    else:
        available = torch.cuda.is_available()

    if not available:
        result = pending_result(backend, f"torch.{backend}.is_available() is false")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return

    torch.manual_seed(SEED)
    if backend == "npu":
        torch.npu.set_device(0)
        device = torch.device("npu:0")
        device_name = torch.npu.get_device_name(0)
    else:
        torch.cuda.set_device(0)
        device = torch.device("cuda:0")
        device_name = torch.cuda.get_device_name(0)

    passed_evidence = f"{backend}_passed"
    failed_evidence = f"{backend}_failed"
    tests: list[dict] = []

    positional = base_test(
        "sinusoidal_fp32_fallback",
        "numerical_precision",
        {
            "time": [0.0, 0.001, 0.01, 0.125, 0.5, 0.999, 1.0],
            "dimension": 256,
            "min_period": 0.004,
            "max_period": 4.0,
            "reference": "CPU float64",
            "candidate": f"{backend.upper()} float32",
        },
    )
    try:
        time_values = torch.tensor(positional["input"]["time"], dtype=torch.float64)
        fraction_ref = torch.linspace(0.0, 1.0, 128, dtype=torch.float64)
        period_ref = 0.004 * (4.0 / 0.004) ** fraction_ref
        phase_ref = (2 * math.pi / period_ref)[None, :] * time_values[:, None]
        reference = torch.cat([phase_ref.sin(), phase_ref.cos()], dim=1)

        time_candidate = time_values.float().to(device)
        fraction = torch.linspace(0.0, 1.0, 128, dtype=torch.float32, device=device)
        period = 0.004 * (4.0 / 0.004) ** fraction
        phase = (2 * math.pi / period)[None, :] * time_candidate[:, None]
        candidate = torch.cat([phase.sin(), phase.cos()], dim=1)
        synchronize(backend)
        positional["metrics"] = numerical_metrics(reference, candidate)
        positional["status"] = "passed"
        positional["evidence_status"] = passed_evidence
    except Exception as exc:
        positional["exception"] = exception_payload(exc)
        positional["evidence_status"] = failed_evidence
    tests.append(positional)

    eager = base_test(
        "eager_fixed_input",
        "operator_implementation",
        {"shape": [128, 128], "dtype": "float32", "warmup": 3, "repeats": 10},
    )
    compile_test = base_test(
        "compile_fixed_input",
        "operator_implementation",
        {"shape": [128, 128], "dtype": "float32", "warmup": 3, "repeats": 10, "mode": "max-autotune"},
    )
    generator = torch.Generator(device="cpu").manual_seed(SEED)
    fixed_cpu = torch.randn(128, 128, generator=generator, dtype=torch.float32)
    fixed = fixed_cpu.to(device)

    def toy(value: torch.Tensor) -> torch.Tensor:
        return torch.tanh(value @ value.transpose(0, 1) / math.sqrt(value.shape[1])) + torch.sin(value)

    eager_output = None
    try:
        reset_peak_memory(backend)
        eager_output, eager_samples = timed(lambda: toy(fixed), backend)
        eager["samples"] = eager_samples
        eager["metrics"] = {
            "median_seconds": statistics.median(eager_samples),
            "p95_seconds": percentile95(eager_samples),
            "finite_output": bool(torch.isfinite(eager_output).all().item()),
        }
        eager["memory"] = {"peak_allocated_bytes": peak_memory(backend)}
        eager["status"] = "passed"
        eager["evidence_status"] = passed_evidence
    except Exception as exc:
        eager["exception"] = exception_payload(exc)
        eager["evidence_status"] = failed_evidence
    tests.append(eager)

    try:
        reset_peak_memory(backend)
        compiled = torch.compile(toy, mode="max-autotune")
        compiled_output, compile_samples = timed(lambda: compiled(fixed), backend)
        compile_test["samples"] = compile_samples
        compile_test["metrics"] = {
            "median_seconds": statistics.median(compile_samples),
            "p95_seconds": percentile95(compile_samples),
            "finite_output": bool(torch.isfinite(compiled_output).all().item()),
        }
        if eager_output is not None:
            compile_test["metrics"].update(numerical_metrics(eager_output, compiled_output))
        compile_test["memory"] = {"peak_allocated_bytes": peak_memory(backend)}
        compile_test["status"] = "passed"
        compile_test["evidence_status"] = passed_evidence
    except Exception as exc:
        compile_test["exception"] = exception_payload(exc)
        compile_test["evidence_status"] = failed_evidence
        compile_test["expected_control_for_npu_guard"] = backend == "npu"
    tests.append(compile_test)

    mismatch = base_test(
        "sdpa_mixed_dtype_control",
        "numerical_precision",
        {"qkv_shape": [2, 4, 16, 32], "query_dtype": "bfloat16", "key_value_dtype": "float32"},
    )
    aligned = base_test(
        "sdpa_aligned_dtype",
        "numerical_precision",
        {"qkv_shape": [2, 4, 16, 32], "query_key_value_dtype": "bfloat16", "reference": "CPU float32"},
    )
    q_cpu = torch.randn(2, 4, 16, 32, generator=generator, dtype=torch.float32)
    k_cpu = torch.randn(2, 4, 16, 32, generator=generator, dtype=torch.float32)
    v_cpu = torch.randn(2, 4, 16, 32, generator=generator, dtype=torch.float32)
    q = q_cpu.to(device=device, dtype=torch.bfloat16)
    k_float = k_cpu.to(device=device, dtype=torch.float32)
    v_float = v_cpu.to(device=device, dtype=torch.float32)

    try:
        mixed_output = F.scaled_dot_product_attention(q, k_float, v_float)
        synchronize(backend)
        mismatch["status"] = "passed"
        mismatch["evidence_status"] = passed_evidence
        mismatch["metrics"] = {"finite_output": bool(torch.isfinite(mixed_output).all().item())}
    except Exception as exc:
        mismatch["exception"] = exception_payload(exc)
        mismatch["evidence_status"] = failed_evidence
        mismatch["expected_control_failure"] = True
    tests.append(mismatch)

    try:
        k = k_float.to(torch.bfloat16)
        v = v_float.to(torch.bfloat16)
        reset_peak_memory(backend)
        aligned_output, aligned_samples = timed(lambda: F.scaled_dot_product_attention(q, k, v), backend)
        reference = F.scaled_dot_product_attention(q_cpu, k_cpu, v_cpu)
        aligned["samples"] = aligned_samples
        aligned["metrics"] = numerical_metrics(reference, aligned_output)
        aligned["metrics"].update(
            median_seconds=statistics.median(aligned_samples),
            p95_seconds=percentile95(aligned_samples),
            finite_output=bool(torch.isfinite(aligned_output).all().item()),
        )
        aligned["memory"] = {"peak_allocated_bytes": peak_memory(backend)}
        aligned["status"] = "passed"
        aligned["evidence_status"] = passed_evidence
    except Exception as exc:
        aligned["exception"] = exception_payload(exc)
        aligned["evidence_status"] = failed_evidence
    tests.append(aligned)

    result = {
        "schema_version": "1.0.0",
        "case": "MINT",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "promotion_status": "exploratory",
        "backend": backend,
        "environment": {
            "device": device_name,
            "torch": torch.__version__,
            f"torch_{backend}": backend_module_version,
            "platform": platform.platform(),
        },
        "tests": tests,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
