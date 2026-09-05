#!/usr/bin/env python

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


SUITES = ("libero_spatial", "libero_object", "libero_goal", "libero_10")
DISPLAY_NAMES = {
    "libero_spatial": "Spatial",
    "libero_object": "Object",
    "libero_goal": "Goal",
    "libero_10": "LIBERO-10",
}
MINT_PUBLISHED = {
    "libero_spatial": 97.4,
    "libero_object": 99.6,
    "libero_goal": 98.2,
    "libero_10": 97.8,
}
PI05_LEROBOT_PUBLISHED = {
    "libero_spatial": 97.0,
    "libero_object": 99.0,
    "libero_goal": 98.0,
    "libero_10": 96.0,
}


def wilson_interval(successes: int, trials: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if trials <= 0:
        return math.nan, math.nan
    p = successes / trials
    denominator = 1 + z**2 / trials
    center = (p + z**2 / (2 * trials)) / denominator
    margin = z * math.sqrt(p * (1 - p) / trials + z**2 / (4 * trials**2)) / denominator
    return 100 * max(0.0, center - margin), 100 * min(1.0, center + margin)


def read_eval(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for item in payload["per_task"]:
        suite = str(item["task_group"])
        if suite not in SUITES:
            continue
        successes = [bool(value) for value in item["metrics"]["successes"]]
        rows.append(
            {
                "suite": suite,
                "task_id": int(item["task_id"]),
                "successes": sum(successes),
                "trials": len(successes),
                "videos": len(item["metrics"].get("video_paths", [])),
                "source": str(path.resolve()),
            }
        )
    return rows


def aggregate(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    task_groups: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        key = (row["suite"], row["task_id"])
        target = task_groups.setdefault(
            key,
            {"suite": row["suite"], "task_id": row["task_id"], "successes": 0, "trials": 0, "videos": 0},
        )
        for field in ("successes", "trials", "videos"):
            target[field] += row[field]

    per_task = []
    for key in sorted(task_groups, key=lambda item: (SUITES.index(item[0]), item[1])):
        row = task_groups[key]
        low, high = wilson_interval(row["successes"], row["trials"])
        row["success_rate_pct"] = 100 * row["successes"] / row["trials"]
        row["wilson_95_low_pct"] = low
        row["wilson_95_high_pct"] = high
        per_task.append(row)

    per_suite = []
    for suite in SUITES:
        suite_rows = [row for row in per_task if row["suite"] == suite]
        successes = sum(row["successes"] for row in suite_rows)
        trials = sum(row["trials"] for row in suite_rows)
        videos = sum(row["videos"] for row in suite_rows)
        low, high = wilson_interval(successes, trials)
        per_suite.append(
            {
                "suite": suite,
                "display_name": DISPLAY_NAMES[suite],
                "successes": successes,
                "trials": trials,
                "success_rate_pct": 100 * successes / trials if trials else math.nan,
                "wilson_95_low_pct": low,
                "wilson_95_high_pct": high,
                "videos": videos,
                "mint_published_pct": MINT_PUBLISHED[suite],
                "pi05_lerobot_published_pct": PI05_LEROBOT_PUBLISHED[suite],
            }
        )
    return per_task, per_suite


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def plot(
    output_dir: Path,
    per_suite: list[dict[str, Any]],
    primary_label: str,
    baseline_by_suite: dict[str, dict[str, Any]] | None = None,
    pi05_by_suite: dict[str, dict[str, Any]] | None = None,
    mint_v043_by_suite: dict[str, dict[str, Any]] | None = None,
    pi05_v043_by_suite: dict[str, dict[str, Any]] | None = None,
) -> None:
    x_values = list(range(len(per_suite)))
    series: list[tuple[str, list[float], str, list[list[float]] | None]] = [
        ("MINT published", [row["mint_published_pct"] for row in per_suite], "#2f6f9f", None),
        (
            "PI0.5 LeRobot published",
            [row["pi05_lerobot_published_pct"] for row in per_suite],
            "#d47a2c",
            None,
        ),
    ]
    if baseline_by_suite:
        baseline = [baseline_by_suite[row["suite"]] for row in per_suite]
        baseline_rates = [row["success_rate_pct"] for row in baseline]
        series.append(
            (
                "MINT Ascend before semantic fix",
                baseline_rates,
                "#9a6aa6",
                [
                    [
                        value - row["wilson_95_low_pct"]
                        for value, row in zip(baseline_rates, baseline, strict=True)
                    ],
                    [
                        row["wilson_95_high_pct"] - value
                        for value, row in zip(baseline_rates, baseline, strict=True)
                    ],
                ],
            )
        )
    aligned_rates = [row["success_rate_pct"] for row in per_suite]
    series.append(
        (
            primary_label,
            aligned_rates,
            "#31845b",
            [
                [
                    value - row["wilson_95_low_pct"]
                    for value, row in zip(aligned_rates, per_suite, strict=True)
                ],
                [
                    row["wilson_95_high_pct"] - value
                    for value, row in zip(aligned_rates, per_suite, strict=True)
                ],
            ],
        )
    )
    if mint_v043_by_suite:
        mint_v043 = [mint_v043_by_suite[row["suite"]] for row in per_suite]
        mint_v043_rates = [row["success_rate_pct"] for row in mint_v043]
        series.append(
            (
                "MINT Ascend (LeRobot 0.4.3)",
                mint_v043_rates,
                "#607d3b",
                [
                    [
                        value - row["wilson_95_low_pct"]
                        for value, row in zip(mint_v043_rates, mint_v043, strict=True)
                    ],
                    [
                        row["wilson_95_high_pct"] - value
                        for value, row in zip(mint_v043_rates, mint_v043, strict=True)
                    ],
                ],
            )
        )
    if pi05_by_suite:
        pi05 = [pi05_by_suite[row["suite"]] for row in per_suite]
        pi05_rates = [row["success_rate_pct"] for row in pi05]
        series.append(
            (
                "PI0.5 Ascend (LeRobot 0.6.2)",
                pi05_rates,
                "#b85c45",
                [
                    [
                        value - row["wilson_95_low_pct"]
                        for value, row in zip(pi05_rates, pi05, strict=True)
                    ],
                    [
                        row["wilson_95_high_pct"] - value
                        for value, row in zip(pi05_rates, pi05, strict=True)
                    ],
                ],
            )
        )
    if pi05_v043_by_suite:
        pi05_v043 = [pi05_v043_by_suite[row["suite"]] for row in per_suite]
        pi05_v043_rates = [row["success_rate_pct"] for row in pi05_v043]
        series.append(
            (
                "PI0.5 Ascend (LeRobot 0.4.3)",
                pi05_v043_rates,
                "#8c6d31",
                [
                    [
                        value - row["wilson_95_low_pct"]
                        for value, row in zip(pi05_v043_rates, pi05_v043, strict=True)
                    ],
                    [
                        row["wilson_95_high_pct"] - value
                        for value, row in zip(pi05_v043_rates, pi05_v043, strict=True)
                    ],
                ],
            )
        )

    width = min(0.22, 0.82 / len(series))
    figure, axis = plt.subplots(figsize=(13, 6), constrained_layout=True)
    center = (len(series) - 1) / 2
    for index, (label, values, color, yerr) in enumerate(series):
        axis.bar(
            [value + (index - center) * width for value in x_values],
            values,
            width,
            label=label,
            color=color,
            yerr=yerr,
            capsize=3,
        )
    axis.set_title("LIBERO published results vs Ascend NPU reproduction")
    axis.set_ylabel("Success rate (%)")
    axis.set_xticks(x_values, [row["display_name"] for row in per_suite])
    axis.set_ylim(80, 102.5)
    axis.grid(axis="y", alpha=0.25)
    axis.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.1),
        ncols=min(3, len(series)),
        fontsize=8,
    )
    figure.savefig(output_dir / "libero_success_comparison.png", dpi=180)
    plt.close(figure)


def main() -> None:
    persistent_root = Path(os.environ["MINT_ASCEND_ROOT"]).resolve()
    parser = argparse.ArgumentParser()
    parser.add_argument("benchmark_dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--primary-label",
        default="MINT Ascend (LeRobot 0.6.2)",
        help="Label for benchmark_dir in tables and plots.",
    )
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        help="Optional pre-fix benchmark directory to include in the comparison report.",
    )
    parser.add_argument(
        "--pi05-dir",
        type=Path,
        help="Optional PI0.5 NPU four-suite benchmark directory to include in the report.",
    )
    parser.add_argument(
        "--mint-v043-dir",
        type=Path,
        help="Optional MINT four-suite benchmark produced with the pinned LeRobot 0.4.3 line.",
    )
    parser.add_argument(
        "--pi05-v043-dir",
        type=Path,
        help="Optional PI0.5 four-suite benchmark produced with the pinned LeRobot 0.4.3 line.",
    )
    args = parser.parse_args()

    benchmark_dir = args.benchmark_dir.resolve()
    output_dir = (args.output_dir or benchmark_dir / "report").resolve()
    for path in (benchmark_dir, output_dir):
        if not path.is_relative_to(persistent_root):
            raise RuntimeError(f"Path is outside persistent root: {path}")

    eval_paths = sorted(benchmark_dir.glob("**/eval_info.json"))
    if not eval_paths:
        raise FileNotFoundError(f"No eval_info.json files below {benchmark_dir}")
    raw_rows = [row for path in eval_paths for row in read_eval(path)]
    per_task, per_suite = aggregate(raw_rows)
    baseline_eval_paths: list[Path] = []
    baseline_by_suite = None
    if args.baseline_dir:
        baseline_dir = args.baseline_dir.resolve()
        if not baseline_dir.is_relative_to(persistent_root):
            raise RuntimeError(f"Path is outside persistent root: {baseline_dir}")
        baseline_eval_paths = sorted(baseline_dir.glob("**/eval_info.json"))
        if not baseline_eval_paths:
            raise FileNotFoundError(f"No eval_info.json files below {baseline_dir}")
        baseline_rows = [row for path in baseline_eval_paths for row in read_eval(path)]
        _, baseline_per_suite = aggregate(baseline_rows)
        baseline_by_suite = {row["suite"]: row for row in baseline_per_suite}
        for row in per_suite:
            baseline = baseline_by_suite[row["suite"]]
            row["pre_fix_successes"] = baseline["successes"]
            row["pre_fix_trials"] = baseline["trials"]
            row["pre_fix_success_rate_pct"] = baseline["success_rate_pct"]
    pi05_eval_paths: list[Path] = []
    pi05_by_suite = None
    if args.pi05_dir:
        pi05_dir = args.pi05_dir.resolve()
        if not pi05_dir.is_relative_to(persistent_root):
            raise RuntimeError(f"Path is outside persistent root: {pi05_dir}")
        pi05_eval_paths = sorted(pi05_dir.glob("**/eval_info.json"))
        if not pi05_eval_paths:
            raise FileNotFoundError(f"No eval_info.json files below {pi05_dir}")
        pi05_rows = [row for path in pi05_eval_paths for row in read_eval(path)]
        _, pi05_per_suite = aggregate(pi05_rows)
        pi05_by_suite = {row["suite"]: row for row in pi05_per_suite}
        for row in per_suite:
            pi05 = pi05_by_suite[row["suite"]]
            row["pi05_npu_successes"] = pi05["successes"]
            row["pi05_npu_trials"] = pi05["trials"]
            row["pi05_npu_success_rate_pct"] = pi05["success_rate_pct"]
    mint_v043_eval_paths: list[Path] = []
    mint_v043_by_suite = None
    if args.mint_v043_dir:
        mint_v043_dir = args.mint_v043_dir.resolve()
        if not mint_v043_dir.is_relative_to(persistent_root):
            raise RuntimeError(f"Path is outside persistent root: {mint_v043_dir}")
        mint_v043_eval_paths = sorted(mint_v043_dir.glob("**/eval_info.json"))
        if not mint_v043_eval_paths:
            raise FileNotFoundError(f"No eval_info.json files below {mint_v043_dir}")
        mint_v043_rows = [row for path in mint_v043_eval_paths for row in read_eval(path)]
        _, mint_v043_per_suite = aggregate(mint_v043_rows)
        mint_v043_by_suite = {row["suite"]: row for row in mint_v043_per_suite}
        missing = set(SUITES) - {suite for suite, row in mint_v043_by_suite.items() if row["trials"]}
        if missing:
            raise RuntimeError(f"MINT LeRobot 0.4.3 benchmark is incomplete: {sorted(missing)}")
        for row in per_suite:
            mint_v043 = mint_v043_by_suite[row["suite"]]
            row["mint_v043_successes"] = mint_v043["successes"]
            row["mint_v043_trials"] = mint_v043["trials"]
            row["mint_v043_success_rate_pct"] = mint_v043["success_rate_pct"]
    pi05_v043_eval_paths: list[Path] = []
    pi05_v043_by_suite = None
    if args.pi05_v043_dir:
        pi05_v043_dir = args.pi05_v043_dir.resolve()
        if not pi05_v043_dir.is_relative_to(persistent_root):
            raise RuntimeError(f"Path is outside persistent root: {pi05_v043_dir}")
        pi05_v043_eval_paths = sorted(pi05_v043_dir.glob("**/eval_info.json"))
        if not pi05_v043_eval_paths:
            raise FileNotFoundError(f"No eval_info.json files below {pi05_v043_dir}")
        pi05_v043_rows = [row for path in pi05_v043_eval_paths for row in read_eval(path)]
        _, pi05_v043_per_suite = aggregate(pi05_v043_rows)
        pi05_v043_by_suite = {row["suite"]: row for row in pi05_v043_per_suite}
        missing = set(SUITES) - {suite for suite, row in pi05_v043_by_suite.items() if row["trials"]}
        if missing:
            raise RuntimeError(f"PI0.5 LeRobot 0.4.3 benchmark is incomplete: {sorted(missing)}")
        for row in per_suite:
            pi05_v043 = pi05_v043_by_suite[row["suite"]]
            row["pi05_v043_successes"] = pi05_v043["successes"]
            row["pi05_v043_trials"] = pi05_v043["trials"]
            row["pi05_v043_success_rate_pct"] = pi05_v043["success_rate_pct"]
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "per_task.csv", per_task)
    write_csv(output_dir / "per_suite.csv", per_suite)
    plot(
        output_dir,
        per_suite,
        args.primary_label,
        baseline_by_suite,
        pi05_by_suite,
        mint_v043_by_suite,
        pi05_v043_by_suite,
    )

    trials = sum(row["trials"] for row in per_suite)
    successes = sum(row["successes"] for row in per_suite)
    payload = {
        "benchmark_dir": str(benchmark_dir),
        "primary_label": args.primary_label,
        "eval_files": [str(path.resolve()) for path in eval_paths],
        "baseline_eval_files": [str(path.resolve()) for path in baseline_eval_paths],
        "pi05_eval_files": [str(path.resolve()) for path in pi05_eval_paths],
        "mint_v043_eval_files": [str(path.resolve()) for path in mint_v043_eval_paths],
        "pi05_v043_eval_files": [str(path.resolve()) for path in pi05_v043_eval_paths],
        "successes": successes,
        "trials": trials,
        "success_rate_pct": 100 * successes / trials,
        "video_count": sum(row["videos"] for row in per_suite),
        "pi05_video_count": (
            sum(row["videos"] for row in pi05_by_suite.values()) if pi05_by_suite else 0
        ),
        "per_suite": per_suite,
        "per_task": per_task,
        "published_sources": {
            "MINT": "arXiv:2602.08602, main LIBERO results",
            "PI0.5 LeRobot": "LeRobot docs/source/pi05.mdx, LIBERO benchmark results",
        },
    }
    (output_dir / "report.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# MINT LIBERO Ascend NPU report",
        "",
        f"- Aggregate: {successes}/{trials} ({100 * successes / trials:.2f}%)",
        f"- Referenced rollout videos: {payload['video_count']}",
        f"- Evaluation files: {len(eval_paths)}",
        "",
    ]
    columns = ["Suite", "Published MINT", "Published PI0.5"]
    if baseline_by_suite:
        columns.append("MINT before fix")
    columns.append(args.primary_label)
    if mint_v043_by_suite:
        columns.append("MINT Ascend 0.4.3")
    if pi05_by_suite:
        columns.append("PI0.5 Ascend 0.6.2")
    if pi05_v043_by_suite:
        columns.append("PI0.5 Ascend 0.4.3")
    columns.extend([f"95% Wilson CI ({args.primary_label})", "Primary videos"])
    lines.extend(
        [
            "| " + " | ".join(columns) + " |",
            "|---|" + "|".join("---:" for _ in columns[1:]) + "|",
        ]
    )
    for row in per_suite:
        values = [
            row["display_name"],
            f"{row['mint_published_pct']:.1f}%",
            f"{row['pi05_lerobot_published_pct']:.1f}%",
        ]
        if baseline_by_suite:
            values.append(
                f"{row['pre_fix_successes']}/{row['pre_fix_trials']} "
                f"({row['pre_fix_success_rate_pct']:.1f}%)"
            )
        values.append(f"{row['successes']}/{row['trials']} ({row['success_rate_pct']:.1f}%)")
        if mint_v043_by_suite:
            values.append(
                f"{row['mint_v043_successes']}/{row['mint_v043_trials']} "
                f"({row['mint_v043_success_rate_pct']:.1f}%)"
            )
        if pi05_by_suite:
            values.append(
                f"{row['pi05_npu_successes']}/{row['pi05_npu_trials']} "
                f"({row['pi05_npu_success_rate_pct']:.1f}%)"
            )
        if pi05_v043_by_suite:
            values.append(
                f"{row['pi05_v043_successes']}/{row['pi05_v043_trials']} "
                f"({row['pi05_v043_success_rate_pct']:.1f}%)"
            )
        values.extend(
            [
                f"[{row['wilson_95_low_pct']:.1f}, {row['wilson_95_high_pct']:.1f}]",
                str(row["videos"]),
            ]
        )
        lines.append("| " + " | ".join(values) + " |")
    (output_dir / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({key: payload[key] for key in ("successes", "trials", "success_rate_pct", "video_count")}, indent=2))


if __name__ == "__main__":
    main()
