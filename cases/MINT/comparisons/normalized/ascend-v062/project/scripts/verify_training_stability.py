#!/usr/bin/env python

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from pathlib import Path


ERROR_PATTERN = re.compile(
    r"out of memory|\boom\b|traceback|runtimeerror|hccl.*error|acl.*error|\bnan\b|\binf\b",
    flags=re.IGNORECASE,
)
STEP_PATTERN = re.compile(
    r"step:(?P<step>[0-9.]+[kKmM]?)\s+smpl:(?P<samples>[0-9.]+[kKmM]?).*?"
    r"updt_s:(?P<update>[0-9.]+).*?step_s:(?P<step_s>[0-9.]+).*?"
    r"smp/s:(?P<throughput>[0-9.]+).*?mem_gb:(?P<memory>[0-9.]+)"
)
PROGRESS_PATTERN = re.compile(r"Training:.*?\|\s*(?P<step>\d+)/(?P<total>\d+)")


def parse_number(value: str) -> float:
    suffix = value[-1].lower()
    multiplier = {"k": 1_000.0, "m": 1_000_000.0}.get(suffix, 1.0)
    return float(value[:-1] if multiplier != 1.0 else value) * multiplier


def find_error_lines(text: str) -> list[str]:
    errors = []
    inside_codec_traceback = False
    for line in text.splitlines():
        lowered = line.lower()
        if "start of libtorchcodec loading traceback" in lowered:
            inside_codec_traceback = True
            continue
        if "end of libtorchcodec loading traceback" in lowered:
            inside_codec_traceback = False
            continue
        if not inside_codec_traceback and ERROR_PATTERN.search(line):
            errors.append(line)
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("session_dir", type=Path)
    parser.add_argument("--minimum-log-points", type=int, default=5)
    parser.add_argument(
        "--jobs",
        nargs="+",
        choices=("mint", "pi05"),
        default=("mint", "pi05"),
        help="Training launcher logs to validate.",
    )
    args = parser.parse_args()

    session_dir = args.session_dir.resolve()
    manifest_path = session_dir / "manifest.txt"
    manifest_text = manifest_path.read_text(encoding="utf-8", errors="replace") if manifest_path.is_file() else ""
    grad_accum_match = re.search(r"^gradient_accumulation_steps=(\d+)$", manifest_text, re.MULTILINE)
    grad_accum = int(grad_accum_match.group(1)) if grad_accum_match else 1
    rows = []
    errors = []
    per_job = {}
    for job in args.jobs:
        log_path = session_dir / f"{job}_launcher.log"
        if not log_path.is_file():
            raise FileNotFoundError(log_path)
        text = log_path.read_text(encoding="utf-8", errors="replace")
        job_rows = []
        for match in STEP_PATTERN.finditer(text):
            row = {key: parse_number(value) for key, value in match.groupdict().items()}
            row["job"] = job
            rows.append(row)
            job_rows.append(row)
        progress_rows = [
            (int(match.group("step")), int(match.group("total")))
            for match in PROGRESS_PATTERN.finditer(text)
        ]
        last_progress_step = max((step for step, _ in progress_rows), default=None)
        total_progress_steps = max((total for _, total in progress_rows), default=None)
        step_seconds = [row["step_s"] for row in job_rows]
        sorted_step_seconds = sorted(step_seconds)
        p95_index = max(0, math.ceil(0.95 * len(sorted_step_seconds)) - 1)
        job_errors = find_error_lines(text)
        errors.extend(f"{job}: {line}" for line in job_errors)
        per_job[job] = {
            "log": str(log_path),
            "log_points": len(job_rows),
            "last_step": job_rows[-1]["step"] if job_rows else None,
            "last_progress_micro_step": last_progress_step,
            "total_micro_steps": total_progress_steps,
            "gradient_accumulation_steps": grad_accum,
            "last_optimizer_update": last_progress_step // grad_accum if last_progress_step is not None else None,
            "mean_step_s": statistics.mean(step_seconds) if step_seconds else None,
            "median_step_s": statistics.median(step_seconds) if step_seconds else None,
            "p95_step_s": sorted_step_seconds[p95_index] if step_seconds else None,
            "mean_samples_per_s": (
                sum(row["throughput"] for row in job_rows) / len(job_rows) if job_rows else None
            ),
            "peak_memory_gib": max((row["memory"] for row in job_rows), default=None),
            "error_lines": len(job_errors),
        }

    stable = all(item["log_points"] >= args.minimum_log_points for item in per_job.values()) and not errors
    outputs_dir = session_dir.parent.parent
    checkpoint_files = sorted(
        [
            *outputs_dir.glob("train/**/model.safetensors"),
            *outputs_dir.glob("mint/train/**/model.safetensors"),
        ],
        key=lambda path: path.stat().st_mtime,
    )
    result = {
        "stable": stable,
        "minimum_log_points": args.minimum_log_points,
        "jobs": per_job,
        "error_lines": errors[:50],
        "finite_metrics": all(
            math.isfinite(value)
            for row in rows
            for key, value in row.items()
            if key != "job"
        ),
        "checkpoint_files_seen": [str(path.resolve()) for path in checkpoint_files[-10:]],
    }
    output_path = session_dir / "stability_report.json"
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    if not stable or not result["finite_metrics"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
