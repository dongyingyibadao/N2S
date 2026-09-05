#!/usr/bin/env python3

import argparse
import json
import math
from pathlib import Path
import shutil
import statistics
import subprocess
import time


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=5)
    args = parser.parse_args()

    result = {"promotion_status": "exploratory", "tools": {}}
    npu_smi = shutil.which("npu-smi")
    if npu_smi is None:
        result["tools"]["npu-smi"] = {"status": "not_available"}
    else:
        samples = []
        last = None
        for _ in range(args.samples):
            started = time.perf_counter()
            last = subprocess.run([npu_smi, "info"], capture_output=True, text=True, check=False)
            samples.append(time.perf_counter() - started)
        output = last.stdout if last is not None else ""
        required_fields = ["NPU", "Name", "Health", "Power(W)", "Temp(C)", "Memory-Usage(MB)"]
        result["tools"]["npu-smi"] = {
            "status": "exploratory_validated" if last and last.returncode == 0 else "failed",
            "path": npu_smi,
            "returncode": last.returncode if last else None,
            "required_fields": {field: field in output for field in required_fields},
            "samples_seconds": samples,
            "median_seconds": statistics.median(samples),
            "p95_seconds": sorted(samples)[math.ceil(0.95 * len(samples)) - 1],
            "stderr": last.stderr[-2000:] if last else "",
        }

    for tool in ("msprof", "msaccucmp"):
        path = shutil.which(tool)
        result["tools"][tool] = {
            "status": "available_unvalidated" if path else "not_available",
            "path": path,
            "warning": "Availability is not profiler/dump overhead validation.",
        }

    try:
        from torch_npu.contrib import transfer_to_npu  # noqa: F401

        available = True
        import_error = None
    except Exception as exc:
        available = False
        import_error = f"{type(exc).__name__}: {exc}"
    result["tools"]["torch_npu.contrib.transfer_to_npu"] = {
        "status": "experimental",
        "import_available": available,
        "import_error": import_error,
        "warning": "Not invoked: isolated functional, numerical, performance and monkey-patch A/B is pending.",
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
