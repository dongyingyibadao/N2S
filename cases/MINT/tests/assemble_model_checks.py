#!/usr/bin/env python3
"""Assemble snapshot/model smoke outputs into the common N2S result schema."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path


ACCEPTANCE = "record_only_no_unified_threshold"


def read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def test_result(test_id: str, classification: str, status: str, input_spec: dict) -> dict:
    return {
        "id": test_id,
        "classification": classification,
        "status": status,
        "evidence_status": "npu_passed" if status == "passed" else "npu_failed",
        "seed": 42,
        "input": input_spec,
        "checkpoint": None,
        "samples": [],
        "metrics": {},
        "memory": {},
        "exception": None,
        "acceptance": ACCEPTANCE,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence_dir = args.evidence_dir
    tests = []

    for version in ("v043", "v062"):
        source_import = read_json(evidence_dir / f"snapshot_import_{version}.json")
        if source_import is None:
            continue
        status = "passed" if source_import.get("status") == "passed" else "failed"
        test = test_result(
            f"snapshot_import_{version}",
            "framework_api",
            status,
            {"expected_source": source_import.get("expected_source")},
        )
        test["metrics"] = {
            "all_modules_from_snapshot": not source_import.get("wrong_source_files", []),
            "imported_files": source_import.get("imported_files", {}),
        }
        test["exception"] = source_import.get("exception")
        tests.append(test)

    ops = read_json(evidence_dir / "snapshot_ops_smoke.json")
    if ops is not None:
        status = "passed" if ops.get("finite_gradients") else "failed"
        test = test_result(
            "snapshot_operator_smoke",
            "operator_implementation",
            status,
            {"source": "ascend-v062 snapshot", "seed": 42},
        )
        test["metrics"] = ops
        tests.append(test)

    model_specs = (
        ("random_weight_inference", "mint_specific_change"),
        ("random_weight_training", "operator_implementation"),
        ("checkpoint_inference", "checkpoint_release_semantics"),
    )
    for name, classification in model_specs:
        model = read_json(evidence_dir / f"{name}.json")
        if model is None or "mode" not in model:
            continue
        finite = model.get("finite_actions", model.get("finite_loss", False))
        if model.get("mode") == "training":
            finite = finite and model.get("finite_output_gradient", False)
        status = "passed" if finite else "failed"
        test = test_result(
            name,
            classification,
            status,
            {
                "batch_size": model.get("batch_size"),
                "image_count": model.get("image_count"),
                "image_dtype": model.get("image_dtype"),
                "token_length": model.get("token_length"),
                "scope": model.get("scope"),
            },
        )
        if name == "checkpoint_inference":
            test["checkpoint"] = {
                "path": model.get("scope", "").removeprefix("pretrained checkpoint: "),
                "sha256": "e0248497a1a9b750249ac65945baa53ab2ad57a8e9941229a7bf3ed0e6d218c9",
            }
        test["samples"] = [model["run_seconds_mean"]]
        test["metrics"] = {
            key: value
            for key, value in model.items()
            if key
            not in {
                "scope",
                "device",
                "batch_size",
                "image_count",
                "image_dtype",
                "token_length",
                "max_memory_gib",
            }
        }
        test["memory"] = {"peak_allocated_gib": model.get("max_memory_gib")}
        tests.append(test)

    prior = read_json(evidence_dir / "prior_run_summary.json")
    if prior is not None:
        training = prior["single_update_training"]
        train_test = test_result(
            "official_checkpoint_dataset_single_update",
            "checkpoint_release_semantics",
            "passed" if training["status"] == "passed" else "failed",
            {"dataset": training["dataset"], "batch_size": training["batch_size"]},
        )
        train_test["checkpoint"] = prior["checkpoint"]
        train_test["samples"] = [training["step_seconds"]]
        train_test["metrics"] = training
        train_test["memory"] = {"peak_allocated_gb": training["peak_memory_gb"]}
        tests.append(train_test)

        libero = prior["libero_three_round_inference"]
        libero_test = test_result(
            "official_checkpoint_libero_three_round",
            "mint_specific_change",
            "passed" if libero["status"] == "passed" else "failed",
            {"suite": libero["suite"], "task_id": libero["task_id"], "scope": libero["scope"]},
        )
        libero_test["checkpoint"] = prior["checkpoint"]
        libero_test["samples"] = [libero["mean_episode_seconds"]] * libero["episodes"]
        libero_test["metrics"] = libero
        tests.append(libero_test)

    result = {
        "schema_version": "1.0.0",
        "case": "MINT",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "promotion_status": "exploratory",
        "backend": "npu",
        "environment": {
            "device": "Ascend910B2C",
            "torch": "2.9.0+cpu",
            "torch_npu": "2.9.0",
            "source": "N2S snapshots plus content-addressed prior run evidence",
        },
        "tests": tests,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
