#!/usr/bin/env python3
import argparse
import hashlib
import json
import sys
from pathlib import Path

import jsonschema


CASE_ROOT = Path(__file__).resolve().parent
N2S_ROOT = CASE_ROOT.parents[1]
sys.path.insert(0, str(N2S_ROOT / "tooling" / "src"))

from n2s_rules.engine import inspect_project  # noqa: E402
from n2s_rules.plugins import load_rule_plugins  # noqa: E402
from n2s_rules.registry import registry_sha256, validate_registry  # noqa: E402


CACHE_RULE = "pytorch.attention.cache-dtype-alignment"
COMPILE_RULE = "pytorch.npu.compile-capability-fallback"
FP64_RULE = "pytorch.npu.sinusoidal-fp64-fallback"
RULE_IDS = (CACHE_RULE, COMPILE_RULE, FP64_RULE)

PROJECTS = (
    {
        "name": "LeRobot",
        "root": "lerobot-4aaff99",
        "expectations": {
            CACHE_RULE: (1, ["PI0"]),
            COMPILE_RULE: (2, ["PI0", "SmolVLA"]),
            FP64_RULE: (1, ["PI0", "SmolVLA"]),
        },
    },
    {
        "name": "OpenPI",
        "root": "openpi-215abfb",
        "expectations": {
            CACHE_RULE: (1, ["PI0"]),
            COMPILE_RULE: (0, ["PI0"]),
            FP64_RULE: (1, ["PI0"]),
        },
    },
)


def _sha256_bytes(content):
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path):
    return _sha256_bytes(path.read_bytes())


def _verify_snapshot(root):
    manifest = root / "SHA256SUMS"
    expected = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        digest, relative = line.split(maxsplit=1)
        relative = relative.lstrip("*")
        if relative in expected or not relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise RuntimeError(f"invalid snapshot hash entry: {relative!r}")
        expected[relative] = digest
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "SHA256SUMS"
    }
    if actual_files != set(expected):
        raise RuntimeError(f"snapshot file set differs for {root.name}")
    for relative, digest in expected.items():
        if _sha256_file(root / relative) != digest:
            raise RuntimeError(f"snapshot hash mismatch: {root.name}/{relative}")
    return len(expected), _sha256_file(manifest)


def _refusal(project, rule_id):
    if project["name"] != "OpenPI" or rule_id != COMPILE_RULE:
        return None
    model_path = CASE_ROOT / project["root"] / "src/openpi/models_pytorch/pi0_pytorch.py"
    config_path = CASE_ROOT / project["root"] / "src/openpi/models/pi0_config.py"
    model = model_path.read_text(encoding="utf-8")
    config = config_path.read_text(encoding="utf-8")
    evidence = {
        "compile_condition_present": "if config.pytorch_compile_mode is not None:" in model,
        "torch_compile_present": "torch.compile(" in model,
        "constructor_device_expression_present": "config.device" in model,
        "config_device_field_present": "device:" in config,
    }
    if evidence != {
        "compile_condition_present": True,
        "torch_compile_present": True,
        "constructor_device_expression_present": False,
        "config_device_field_present": False,
    }:
        raise RuntimeError(f"OpenPI compile refusal evidence drifted: {evidence}")
    return {
        "reason": "The compile block is controlled by config.pytorch_compile_mode, and no constructor-time config.device field or expression proves the execution backend.",
        "fail_closed": True,
        "evidence": evidence,
    }


def _validate_rule(project_root, rule, findings):
    plugins = load_rule_plugins(rule.package, rule.manifest)
    grouped = {}
    for finding in findings:
        grouped.setdefault(finding["path"], []).append(finding)
    changes = []
    for relative, file_findings in sorted(grouped.items()):
        source = (project_root / relative).read_text(encoding="utf-8")
        errors = plugins["validator"].validate_before(source, relative, file_findings)
        if errors:
            raise RuntimeError(f"{rule.manifest['id']} before validation failed for {relative}: {errors}")
        transformed = plugins["codemod"].transform(source, relative, file_findings)
        errors = plugins["validator"].validate_after(source, transformed, relative, file_findings)
        if errors:
            raise RuntimeError(f"{rule.manifest['id']} after validation failed for {relative}: {errors}")
        if plugins["detector"].detect(transformed, relative):
            raise RuntimeError(f"{rule.manifest['id']} is not idempotent for {relative}")
        changes.append(
            {
                "path": relative,
                "source_sha256": _sha256_bytes(source.encode("utf-8")),
                "transformed_sha256": _sha256_bytes(transformed.encode("utf-8")),
                "adapters": sorted(
                    {
                        finding.get("metadata", {}).get("adapter", "default")
                        for finding in file_findings
                    }
                ),
            }
        )
    return changes


def build_report():
    rules_root = N2S_ROOT / "rules"
    _, packages = validate_registry(rules_root)
    by_id = {package.manifest["id"]: package for package in packages}
    projects = []
    for project in PROJECTS:
        project_root = CASE_ROOT / project["root"]
        file_count, manifest_hash = _verify_snapshot(project_root)
        inspection = inspect_project(project_root, packages, rule_ids=RULE_IDS)
        if inspection["scan_errors"]:
            raise RuntimeError(f"scan errors for {project['name']}: {inspection['scan_errors']}")
        rule_results = []
        for rule_id in RULE_IDS:
            expected_count, families = project["expectations"][rule_id]
            findings = [finding for finding in inspection["findings"] if finding["rule_id"] == rule_id]
            if len(findings) != expected_count:
                raise RuntimeError(
                    f"{project['name']} {rule_id}: expected {expected_count} findings, got {len(findings)}"
                )
            refusal = _refusal(project, rule_id)
            if not findings and refusal is None:
                raise RuntimeError(f"unexplained detector refusal: {project['name']} {rule_id}")
            changes = _validate_rule(project_root, by_id[rule_id], findings) if findings else []
            rule_results.append(
                {
                    "rule_id": rule_id,
                    "outcome": "matched" if findings else "rejected",
                    "expected_finding_count": expected_count,
                    "observed_finding_count": len(findings),
                    "model_families": families,
                    "findings": findings,
                    "candidate_changes": changes,
                    "validation": "passed",
                    "refusal": refusal,
                }
            )
        projects.append(
            {
                "name": project["name"],
                "root": project["root"],
                "remote": (project_root / "REMOTE").read_text(encoding="utf-8").strip(),
                "revision": (project_root / "REVISION").read_text(encoding="utf-8").strip(),
                "snapshot_manifest_sha256": manifest_hash,
                "snapshot_file_count": file_count,
                "snapshot_hashes_verified": True,
                "rule_results": rule_results,
            }
        )
    report = {
        "schema_version": "1.0.0",
        "status": "passed",
        "registry_sha256": registry_sha256(rules_root),
        "projects": projects,
    }
    schema = json.loads((CASE_ROOT / "static-validation.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(report)
    return report


def main():
    parser = argparse.ArgumentParser(description="Validate pinned non-MINT sources against N2S candidate rules")
    parser.add_argument("--output", type=Path, default=CASE_ROOT / "reports" / "static_validation.json")
    args = parser.parse_args()
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(args.output), "projects": len(report["projects"])}))


if __name__ == "__main__":
    main()
