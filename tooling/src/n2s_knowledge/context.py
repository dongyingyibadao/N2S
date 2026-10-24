"""Explicit, read-only target context and explainable retrieval ordering.

Literal agreement with documented metadata is not a compatibility or runtime claim.
Missing metadata remains unknown; different versions never exclude a source.
"""

import json
from pathlib import Path


class ContextError(ValueError):
    pass


SOFTWARE_FIELDS = ("cann", "pytorch", "torch_npu", "framework")
PROFILE_FIELDS = {"task", "model", "mode", "device", "software_versions"}


def target_profile(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - PROFILE_FIELDS:
        raise ContextError("Target profile must be a JSON object with task, model, mode, device and/or software_versions")
    result = {}
    for key in ("task", "model", "mode", "device"):
        if key in value:
            if not isinstance(value[key], str) or not value[key].strip():
                raise ContextError(f"Target profile {key} must be a nonempty string")
            result[key] = value[key].strip()
    if "software_versions" in value:
        versions = value["software_versions"]
        if not isinstance(versions, dict) or set(versions) - set(SOFTWARE_FIELDS):
            raise ContextError("Target profile software_versions supports cann, pytorch, torch_npu and framework")
        result["software_versions"] = {}
        for key, version in versions.items():
            if not isinstance(version, str) or not version.strip():
                raise ContextError(f"Target profile software_versions.{key} must be a nonempty string")
            result["software_versions"][key] = version.strip()
    if not any(key != "software_versions" for key in result) and not result.get("software_versions"):
        raise ContextError("Target profile must describe at least one target field")
    return result


def load_target_profile(path):
    if path is None:
        return None
    try:
        return target_profile(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError) as error:
        if isinstance(error, ContextError):
            raise
        raise ContextError(f"Cannot read target profile: {error}") from error


def empty_versions():
    return {field: [] for field in SOFTWARE_FIELDS}


def documented_tasks(modes, entry_type=None):
    tasks = []
    if "training" in modes:
        tasks.append("training")
    if any("inference" in mode for mode in modes):
        tasks.append("inference")
    if entry_type == "performance_claim":
        tasks.append("performance")
    return tasks


def _literal(value):
    return " ".join(value.casefold().split())


def _comparison(field, requested, documented):
    documented = [str(value) for value in documented if value is not None and str(value).strip()]
    if not documented:
        status, reason = "unknown", "No structured value is documented; read the source conditions and implementation."
    elif _literal(requested) in {_literal(value) for value in documented}:
        status, reason = "matched", "Literal documented value agrees; runtime applicability remains unverified."
    else:
        status, reason = "different", "Documented values differ; this is not a determination of incompatibility."
    return {"field": field, "target": requested, "documented": documented, "status": status, "reason": reason}


def rank_results(results, profile=None):
    profile = target_profile(profile)
    for result in results:
        # Also keep a deterministic order when no target context is requested.
        result.pop("context_comparison", None)
        result.pop("context_score", None)
    if profile:
        for result in results:
            fields = []
            for key, result_key in (("task", "tasks"), ("model", "models"), ("mode", "modes"), ("device", "devices")):
                if key in profile:
                    fields.append(_comparison(key, profile[key], result.get(result_key, [])))
            versions = result.get("software_versions", {})
            for field, value in profile.get("software_versions", {}).items():
                fields.append(_comparison(f"software_versions.{field}", value, versions.get(field, [])))
            counts = {status: sum(field["status"] == status for field in fields)
                      for status in ("matched", "different", "unknown")}
            result["context_comparison"] = {"fields": fields, "summary": counts, "compatibility": "not_determined"}
            result["context_score"] = sum(
                (3 if field["field"] in {"task", "model", "mode"} else 1) if field["status"] == "matched"
                else -1 if field["status"] == "different" else 0 for field in fields
            )
    results.sort(key=lambda item: (-(item.get("context_score", 0)), item["result_kind"], item["source"], item["path"], item["title"]))
    return results


CONTEXT_POLICY = ("Soft ordering by literal documented metadata only; differences and unknown values remain in results. "
                  "Versions, aliases, ranges and code-path applicability still require source review; no compatibility or runtime approval is inferred.")
