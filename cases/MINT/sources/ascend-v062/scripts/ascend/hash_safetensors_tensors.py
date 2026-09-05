#!/usr/bin/env python3

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from safetensors import safe_open


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hash safetensors values independently of file header and tensor layout order."
    )
    parser.add_argument("path", type=Path)
    parser.add_argument(
        "--include-prefix",
        default=None,
        help="Only hash tensor keys with this prefix.",
    )
    args = parser.parse_args()

    digest = hashlib.sha256()
    dtype_counts: Counter[str] = Counter()
    parameter_count = 0
    with safe_open(args.path, framework="pt", device="cpu") as checkpoint:
        keys = sorted(
            key
            for key in checkpoint.keys()
            if args.include_prefix is None or key.startswith(args.include_prefix)
        )
        if not keys:
            raise ValueError(f"No tensors matched prefix: {args.include_prefix!r}")
        metadata = checkpoint.metadata()
        for key in keys:
            tensor = checkpoint.get_tensor(key)
            digest.update(key.encode("utf-8"))
            digest.update(b"\0")
            digest.update(str(tensor.dtype).encode("ascii"))
            digest.update(b"\0")
            digest.update(json.dumps(list(tensor.shape), separators=(",", ":")).encode("ascii"))
            digest.update(b"\0")
            digest.update(memoryview(tensor.numpy()))
            dtype_counts[str(tensor.dtype)] += 1
            parameter_count += tensor.numel()

    print(
        json.dumps(
            {
                "path": str(args.path.resolve()),
                "file_size": args.path.stat().st_size,
                "tensor_count": len(keys),
                "parameter_count": parameter_count,
                "dtype_counts": dict(sorted(dtype_counts.items())),
                "metadata": metadata,
                "include_prefix": args.include_prefix,
                "canonical_tensor_sha256": digest.hexdigest(),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
