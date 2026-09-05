#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path

import jsonschema


CUDA_ROOT = Path(__file__).resolve().parent
CASE_ROOT = CUDA_ROOT.parent
RESULT_SCHEMA = json.loads((CASE_ROOT / "schemas" / "result.schema.json").read_text(encoding="utf-8"))
MANIFEST_SCHEMA = json.loads((CUDA_ROOT / "cuda-validation.schema.json").read_text(encoding="utf-8"))

REQUIRED_RESULTS = {
    "candidate_checks.json": [
        "sinusoidal_fp32_fallback",
        "eager_fixed_input",
        "compile_fixed_input",
        "sdpa_mixed_dtype_control",
        "sdpa_aligned_dtype",
    ],
    "cache_dtype_operator_ab.json": [
        "cache_dtype_functional_ab",
        "cache_dtype_cast_overhead_ab",
        "cache_dtype_already_aligned_control",
    ],
    "runtime_rule_ab.json": [
        "sinusoidal_fp64_functional_ab",
        "sinusoidal_fp64_performance_ab",
        "compile_capability_ab",
    ],
}

REQUIRED_LOGS = {
    *(path.removesuffix(".json") + ".log" for path in REQUIRED_RESULTS),
    "nvidia_smi.log",
    "pip_freeze.log",
    "preflight.json",
    "install.log",
    "harness_exit_code.txt",
    "bundle_verification.log",
}


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description="Validate and summarize a CUDA operator/block A/B capture")
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--harness-exit-code", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    validator = jsonschema.Draft202012Validator(
        RESULT_SCHEMA,
        format_checker=jsonschema.FormatChecker(),
    )
    records = []
    environments = []
    for filename, expected_test_ids in REQUIRED_RESULTS.items():
        path = args.results / filename
        if not path.is_file():
            raise RuntimeError(f"required CUDA result is missing: {filename}")
        result = json.loads(path.read_text(encoding="utf-8"))
        errors = sorted(validator.iter_errors(result), key=lambda error: list(error.absolute_path))
        if errors:
            raise RuntimeError(f"{filename} does not match result.schema.json: {errors[0].message}")
        if result["backend"] != "cuda":
            raise RuntimeError(f"{filename} backend is not cuda")
        statuses = [test["status"] for test in result["tests"]]
        if "pending_cuda" in statuses:
            raise RuntimeError(f"{filename} contains pending_cuda on the capture host")
        test_ids = [test["id"] for test in result["tests"]]
        if test_ids != expected_test_ids:
            raise RuntimeError(f"{filename} expected tests {expected_test_ids}, got {test_ids}")
        for test in result["tests"]:
            if test["checkpoint"] is not None:
                raise RuntimeError(f"{filename}:{test['id']} must not record a checkpoint in block-only mode")
        environment = result["environment"]
        environments.append(environment)
        records.append(
            {
                "path": filename,
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
                "test_ids": test_ids,
                "test_statuses": statuses,
            }
        )

    reference = next(environment for environment in environments if "cuda_runtime" in environment)
    for environment in environments:
        for key in ("device", "torch"):
            if environment.get(key) != reference.get(key):
                raise RuntimeError(f"CUDA environment mismatch for {key}: {environment.get(key)!r}")
        if "cuda_runtime" in environment and environment["cuda_runtime"] != reference["cuda_runtime"]:
            raise RuntimeError("CUDA runtime differs across result files")

    logs = []
    for filename in sorted(REQUIRED_LOGS):
        path = args.results / filename
        if not path.is_file():
            raise RuntimeError(f"required CUDA log is missing: {filename}")
        logs.append({"path": filename, "sha256": sha256_file(path), "size_bytes": path.stat().st_size})

    manifest = {
        "schema_version": "1.0.0",
        "status": "captured",
        "backend": "cuda",
        "scope": "operator_block_ab",
        "model_execution": False,
        "model_parameters_loaded": False,
        "harness_exit_code": args.harness_exit_code,
        "environment": {
            "device": reference["device"],
            "torch": reference["torch"],
            "cuda_runtime": reference["cuda_runtime"],
            "cudnn": reference.get("cudnn"),
            "python": reference.get("python"),
            "platform": reference.get("platform"),
        },
        "results": records,
        "logs": logs,
    }
    jsonschema.Draft202012Validator(MANIFEST_SCHEMA).validate(manifest)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "captured", "results": len(records), "logs": len(logs)}, sort_keys=True))


if __name__ == "__main__":
    main()
