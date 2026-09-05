#!/usr/bin/env python3
import importlib.metadata
import json
import platform
import sys

import torch


EXPECTED = {
    "torch": "2.9.0",
    "triton": "3.5.0",
    "jsonschema": "4.26.0",
}


def normalized(version):
    return version.split("+", 1)[0]


def main():
    if sys.version_info[:2] != (3, 12):
        raise SystemExit(f"Python 3.12 is required, got {platform.python_version()}")
    versions = {name: importlib.metadata.version(name) for name in EXPECTED}
    mismatches = {
        name: {"expected": expected, "observed": versions[name]}
        for name, expected in EXPECTED.items()
        if normalized(versions[name]) != expected
    }
    if mismatches:
        raise SystemExit(f"dependency version mismatch: {json.dumps(mismatches, sort_keys=True)}")
    if not torch.cuda.is_available():
        raise SystemExit("torch.cuda.is_available() is false")
    if torch.version.cuda != "12.8":
        raise SystemExit(f"CUDA 12.8 PyTorch build required, got {torch.version.cuda!r}")
    result = {
        "status": "passed",
        "scope": "operator_block_ab",
        "model_execution": False,
        "model_parameters_loaded": False,
        "python": platform.python_version(),
        "versions": versions,
        "torch_cuda": torch.version.cuda,
        "cudnn": torch.backends.cudnn.version(),
        "device": torch.cuda.get_device_name(0),
        "device_count": torch.cuda.device_count(),
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
