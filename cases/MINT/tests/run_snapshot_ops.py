#!/usr/bin/env python3

import argparse
import runpy

import torch
import torch_npu  # noqa: F401


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("script")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    torch.manual_seed(args.seed)
    torch.npu.manual_seed_all(args.seed)
    runpy.run_path(args.script, run_name="__main__")


if __name__ == "__main__":
    main()
