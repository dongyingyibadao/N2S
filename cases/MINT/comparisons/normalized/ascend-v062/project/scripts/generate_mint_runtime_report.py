#!/usr/bin/env python

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def read_result(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace").rstrip()
    start = text.rfind("\n{")
    if start < 0:
        raise ValueError(f"No JSON result found in {path}")
    return json.loads(text[start + 1 :])


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def plot(path: Path, rows: list[dict[str, Any]]) -> None:
    batches = [row["batch_size"] for row in rows]
    labels = [str(batch) for batch in batches]
    figure, axes = plt.subplots(1, 3, figsize=(12.5, 4.2), constrained_layout=True)

    axes[0].plot(labels, [row["chunk_seconds_mean"] for row in rows], marker="o", label="Mean")
    axes[0].plot(labels, [row["chunk_seconds_p95"] for row in rows], marker="s", label="P95")
    axes[0].set_title("Action-chunk latency")
    axes[0].set_xlabel("Batch size")
    axes[0].set_ylabel("Seconds per batch")
    axes[0].legend()

    axes[1].bar(labels, [row["samples_per_second"] for row in rows], color="#2f6f9f")
    axes[1].set_title("Inference throughput")
    axes[1].set_xlabel("Batch size")
    axes[1].set_ylabel("Samples per second")

    axes[2].bar(labels, [row["max_memory_gib"] for row in rows], color="#31845b")
    axes[2].set_title("Peak allocated memory")
    axes[2].set_xlabel("Batch size")
    axes[2].set_ylabel("GiB")

    for axis in axes:
        axis.grid(axis="y", alpha=0.25)
    figure.suptitle("MINT Ascend 910B inference scaling during concurrent LIBERO evaluation")
    figure.savefig(path, dpi=180)
    plt.close(figure)


def main() -> None:
    persistent_root = Path(os.environ["MINT_ASCEND_ROOT"]).resolve()
    parser = argparse.ArgumentParser()
    parser.add_argument("benchmark_dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    benchmark_dir = args.benchmark_dir.resolve()
    output_dir = (args.output_dir or benchmark_dir / "report").resolve()
    for path in (benchmark_dir, output_dir):
        if not path.is_relative_to(persistent_root):
            raise RuntimeError(f"Path is outside persistent root: {path}")

    log_paths = sorted(benchmark_dir.glob("inference_fp32_batch*_concurrent_eval.log"))
    if not log_paths:
        raise FileNotFoundError(f"No concurrent inference logs below {benchmark_dir}")

    rows = []
    for log_path in log_paths:
        result = read_result(log_path)
        batch_size = int(result["batch_size"])
        mean_seconds = float(result["run_seconds_mean"])
        rows.append(
            {
                "batch_size": batch_size,
                "chunk_seconds_mean": mean_seconds,
                "chunk_seconds_median": float(result["run_seconds_median"]),
                "chunk_seconds_p95": float(result["run_seconds_p95"]),
                "chunk_seconds_min": float(result["run_seconds_min"]),
                "chunk_seconds_max": float(result["run_seconds_max"]),
                "samples_per_second": batch_size / mean_seconds,
                "per_sample_seconds": mean_seconds / batch_size,
                "max_memory_gib": float(result["max_memory_gib"]),
                "build_seconds": float(result["build_seconds"]),
                "warmup_runs": int(result["warmup_runs"]),
                "timed_runs": int(result["timed_runs"]),
                "finite_actions": bool(result["finite_actions"]),
                "source_log": str(log_path),
            }
        )
    rows.sort(key=lambda row: row["batch_size"])
    baseline = rows[0]["samples_per_second"]
    for row in rows:
        row["throughput_speedup_vs_batch1"] = row["samples_per_second"] / baseline

    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "runtime_scaling.csv", rows)
    payload = {
        "scope": "MINT public LIBERO checkpoint on one Ascend 910B2C",
        "concurrent_load": "separate NPU running the 200-episode LIBERO benchmark",
        "checkpoint_build_time_excluded_from_chunk_latency": True,
        "rows": rows,
    }
    (output_dir / "runtime_scaling.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    plot(output_dir / "runtime_scaling.png", rows)
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
