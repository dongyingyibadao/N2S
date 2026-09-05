import difflib
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import libcst as cst

from .plugins import load_rule_plugins
from .registry import registry_sha256


EXCLUDED_DIRECTORIES = {
    ".git", ".hg", ".mypy_cache", ".n2s", ".pytest_cache", ".ruff_cache",
    ".tox", ".venv", "__pycache__", "build", "dist", "node_modules", "venv",
}


class EngineError(RuntimeError):
    pass


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _run_id():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def _sha256_bytes(content):
    return hashlib.sha256(content).hexdigest()


def _sha256_text(content):
    return _sha256_bytes(content.encode("utf-8"))


def _read_source(path):
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise EngineError(f"cannot read Python source {path}: {error}") from error


def _write_json(path, value):
    path = Path(path)
    content = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    mode = path.stat().st_mode if path.exists() else None
    _atomic_write_bytes(path, content, mode)


def _iter_python_files(project):
    for root, directories, files in os.walk(project):
        directories[:] = sorted(directory for directory in directories if directory not in EXCLUDED_DIRECTORIES)
        root_path = Path(root)
        for filename in sorted(files):
            if filename.endswith(".py"):
                yield root_path / filename


def _select_rules(packages, rule_ids=None, statuses=None):
    by_id = {rule.manifest["id"]: rule for rule in packages}
    if rule_ids:
        missing = sorted(set(rule_ids) - set(by_id))
        if missing:
            raise EngineError(f"unknown rule ids: {', '.join(missing)}")
        selected = [by_id[rule_id] for rule_id in sorted(set(rule_ids))]
    else:
        selected = sorted(packages, key=lambda rule: rule.manifest["id"])
    if statuses is not None:
        selected = [rule for rule in selected if rule.manifest["status"] in statuses]
    return selected


def inspect_project(project, packages, rule_ids=None, statuses=None):
    project = Path(project).resolve()
    if not project.is_dir():
        raise EngineError(f"project is not a directory: {project}")
    selected = _select_rules(packages, rule_ids, statuses)
    findings = []
    scan_errors = []
    plugins = {rule.manifest["id"]: load_rule_plugins(rule.package, rule.manifest) for rule in selected}
    for source_path in _iter_python_files(project):
        relative = source_path.relative_to(project).as_posix()
        try:
            source = _read_source(source_path)
            cst.parse_module(source)
        except (EngineError, cst.ParserSyntaxError) as error:
            scan_errors.append({"path": relative, "error": str(error)})
            continue
        for rule in selected:
            rule_id = rule.manifest["id"]
            for finding in plugins[rule_id]["detector"].detect(source, relative):
                findings.append(
                    {
                        **finding,
                        "rule_id": rule_id,
                        "rule_version": rule.manifest["version"],
                        "rule_status": rule.manifest["status"],
                        "risk": rule.manifest["risk"],
                        "path": relative,
                    }
                )
    findings.sort(key=lambda item: (item["rule_id"], item["path"], item["line"], item["id"]))
    return {
        "schema_version": "1.0.0",
        "generated_at": _utc_now(),
        "project": str(project),
        "rules": [rule.manifest["id"] for rule in selected],
        "findings": findings,
        "scan_errors": scan_errors,
    }


def create_plan(project, rules_root, packages, rule_ids=None, include_candidates=False):
    statuses = {"approved", "candidate"} if include_candidates else {"approved"}
    inspection = inspect_project(project, packages, rule_ids=rule_ids, statuses=statuses)
    project = Path(inspection["project"])
    selected = _select_rules(packages, rule_ids, statuses)
    by_id = {rule.manifest["id"]: rule for rule in selected}
    grouped = {}
    for finding in inspection["findings"]:
        grouped.setdefault((finding["rule_id"], finding["path"]), []).append(finding)
    changes = []
    for (rule_id, relative), findings in sorted(grouped.items()):
        rule = by_id[rule_id]
        manifest = rule.manifest
        plugins = load_rule_plugins(rule.package, manifest)
        source_path = project / relative
        before = _read_source(source_path)
        errors = plugins["validator"].validate_before(before, relative, findings)
        if errors:
            raise EngineError(f"{rule_id} rejected {relative} before transform: {errors}")
        try:
            after = plugins["codemod"].transform(before, relative, findings)
        except Exception as error:
            raise EngineError(f"{rule_id} failed to transform {relative}: {error}") from error
        errors = plugins["validator"].validate_after(before, after, relative, findings)
        if errors:
            raise EngineError(f"{rule_id} rejected {relative} after transform: {errors}")
        if before == after:
            raise EngineError(f"{rule_id} reported findings but made no change to {relative}")
        eligible = manifest["status"] == "approved" and manifest["automation"]["auto_apply"] and manifest["approval"] is not None
        changes.append(
            {
                "rule_id": rule_id,
                "rule_version": manifest["version"],
                "rule_status": manifest["status"],
                "path": relative,
                "before_sha256": _sha256_text(before),
                "after_sha256": _sha256_text(after),
                "eligible_for_apply": eligible,
                "finding_ids": [finding["id"] for finding in findings],
                "findings": findings,
                "diff": "".join(
                    difflib.unified_diff(
                        before.splitlines(keepends=True),
                        after.splitlines(keepends=True),
                        fromfile=f"a/{relative}",
                        tofile=f"b/{relative}",
                    )
                ),
            }
        )
    return {
        "schema_version": "1.0.0",
        "generated_at": _utc_now(),
        "project": str(project),
        "rules_root": str(Path(rules_root).resolve()),
        "registry_sha256": registry_sha256(rules_root),
        "include_candidates": include_candidates,
        "scan_errors": inspection["scan_errors"],
        "changes": changes,
    }


def _safe_project_path(project, relative):
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise EngineError(f"unsafe project-relative path: {relative}")
    resolved = (project / relative_path).resolve()
    try:
        resolved.relative_to(project)
    except ValueError as error:
        raise EngineError(f"path resolves outside project: {relative}") from error
    return resolved


def _atomic_write_bytes(path, content, mode=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _load_json(path, label):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EngineError(f"cannot read {label} {path}: {error}") from error
    if not isinstance(value, dict):
        raise EngineError(f"{label} must be a JSON object: {path}")
    return value


def apply_plan(plan_path, packages, rules_root, report_path=None):
    plan_path = Path(plan_path).resolve()
    plan = _load_json(plan_path, "plan")
    project = Path(plan.get("project", "")).resolve()
    if not project.is_dir():
        raise EngineError(f"plan project is not a directory: {project}")
    if plan.get("rules_root") != str(Path(rules_root).resolve()):
        raise EngineError("plan rules_root differs from the active rules root")
    if plan.get("registry_sha256") != registry_sha256(rules_root):
        raise EngineError("registry changed after the plan was generated")
    if plan.get("scan_errors"):
        raise EngineError("plan contains source scan errors")
    changes = plan.get("changes")
    if not isinstance(changes, list) or not changes:
        raise EngineError("plan contains no changes")
    rule_ids = {change.get("rule_id") for change in changes}
    if len(rule_ids) != 1:
        raise EngineError("apply accepts exactly one approved rule per plan")
    rule_id = next(iter(rule_ids))
    by_id = {rule.manifest["id"]: rule for rule in packages}
    rule = by_id.get(rule_id)
    if rule is None:
        raise EngineError(f"rule is no longer registered: {rule_id}")
    manifest = rule.manifest
    if manifest["status"] != "approved" or not manifest["automation"]["auto_apply"] or manifest["approval"] is None:
        raise EngineError(f"rule is not approved for automatic application: {rule_id}")
    if not manifest["verification"]["commands"]:
        raise EngineError(f"approved rule has no verification commands: {rule_id}")
    if any(not change.get("eligible_for_apply") for change in changes):
        raise EngineError("plan contains review-only changes")
    if any(change.get("rule_version") != manifest["version"] or change.get("rule_status") != "approved" for change in changes):
        raise EngineError("rule version or status changed after planning")

    plugins = load_rule_plugins(rule.package, manifest)
    prepared = []
    for change in changes:
        relative = change["path"]
        source_path = _safe_project_path(project, relative)
        if not source_path.is_file() or source_path.is_symlink():
            raise EngineError(f"source is missing or is a symlink: {relative}")
        before = _read_source(source_path)
        if _sha256_text(before) != change["before_sha256"]:
            raise EngineError(f"source changed after planning: {relative}")
        current_findings = plugins["detector"].detect(before, relative)
        planned_ids = change["finding_ids"]
        if [finding["id"] for finding in current_findings] != planned_ids:
            raise EngineError(f"detector findings changed after planning: {relative}")
        errors = plugins["validator"].validate_before(before, relative, current_findings)
        if errors:
            raise EngineError(f"before validation failed for {relative}: {errors}")
        after = plugins["codemod"].transform(before, relative, current_findings)
        errors = plugins["validator"].validate_after(before, after, relative, current_findings)
        if errors:
            raise EngineError(f"after validation failed for {relative}: {errors}")
        if _sha256_text(after) != change["after_sha256"]:
            raise EngineError(f"codemod output changed after planning: {relative}")
        prepared.append((change, source_path, before.encode("utf-8"), after.encode("utf-8"), source_path.stat().st_mode))

    run_id = _run_id()
    backup_root = project / ".n2s" / "backups" / run_id
    if report_path is None:
        report_path = project / ".n2s" / "reports" / f"{run_id}.json"
    else:
        report_path = Path(report_path).resolve()
    if report_path == plan_path or any(report_path == source_path for _, source_path, _, _, _ in prepared):
        raise EngineError("report path must not overwrite the plan or a changed source file")
    report = {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "started_at": _utc_now(),
        "status": "applying",
        "project": str(project),
        "rule_id": rule_id,
        "rule_version": manifest["version"],
        "plan": str(plan_path),
        "registry_sha256": plan["registry_sha256"],
        "files": [],
        "verification": [],
    }
    written = []
    try:
        for change, source_path, before_bytes, after_bytes, mode in prepared:
            backup_path = backup_root / change["path"]
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, backup_path)
            _atomic_write_bytes(source_path, after_bytes, mode)
            written.append((source_path, backup_path, mode))
            report["files"].append(
                {
                    "path": change["path"],
                    "before_sha256": change["before_sha256"],
                    "after_sha256": change["after_sha256"],
                    "backup": str(backup_path),
                }
            )
        for command in manifest["verification"]["commands"]:
            completed = subprocess.run(command, cwd=project, text=True, capture_output=True, timeout=600, check=False)
            command_result = {
                "command": command,
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
            report["verification"].append(command_result)
            if completed.returncode != 0:
                raise EngineError(f"verification command failed ({completed.returncode}): {command}")
        report["status"] = "applied"
        report["completed_at"] = _utc_now()
        _write_json(report_path, report)
        return report, report_path
    except Exception as error:
        rollback_errors = []
        for source_path, backup_path, mode in reversed(written):
            try:
                _atomic_write_bytes(source_path, backup_path.read_bytes(), mode)
            except Exception as rollback_error:
                rollback_errors.append(f"{source_path}: {rollback_error}")
        report["status"] = "rollback_failed" if rollback_errors else "rolled_back_on_failure"
        report["error"] = str(error)
        report["rollback_errors"] = rollback_errors
        report["completed_at"] = _utc_now()
        _write_json(report_path, report)
        raise EngineError(f"apply failed; report written to {report_path}: {error}") from error


def rollback_report(report_path):
    report_path = Path(report_path).resolve()
    report = _load_json(report_path, "apply report")
    if report.get("status") != "applied":
        raise EngineError(f"report is not in applied state: {report.get('status')}")
    project = Path(report.get("project", "")).resolve()
    prepared = []
    for file_record in report.get("files", []):
        source_path = _safe_project_path(project, file_record["path"])
        backup_path = Path(file_record["backup"]).resolve()
        if not source_path.is_file() or source_path.is_symlink():
            raise EngineError(f"current source is missing or is a symlink: {file_record['path']}")
        current = source_path.read_bytes()
        if _sha256_bytes(current) != file_record["after_sha256"]:
            raise EngineError(f"refusing to overwrite post-apply edits: {file_record['path']}")
        if not backup_path.is_file() or _sha256_bytes(backup_path.read_bytes()) != file_record["before_sha256"]:
            raise EngineError(f"backup is missing or corrupt: {backup_path}")
        prepared.append((source_path, backup_path, source_path.stat().st_mode))
    for source_path, backup_path, mode in prepared:
        _atomic_write_bytes(source_path, backup_path.read_bytes(), mode)
    report["status"] = "rolled_back"
    report["rolled_back_at"] = _utc_now()
    _write_json(report_path, report)
    return report
