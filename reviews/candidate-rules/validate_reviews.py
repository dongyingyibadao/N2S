#!/usr/bin/env python3
import json
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parent
EVIDENCE_LEVELS = {"static": 0, "module": 1, "integration": 2, "model": 3}


def main():
    schema = json.loads((ROOT / "review.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    reviewed = []
    for path in sorted(ROOT.glob("*.review.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        errors = sorted(validator.iter_errors(value), key=lambda error: list(error.absolute_path))
        if errors:
            raise SystemExit(f"{path.name}: {errors[0].message}")
        if value["decision"] == "approved" and any(item is None for item in value["thresholds"].values()):
            raise SystemExit(f"{path.name}: approved decision requires all threshold objects")
        if value["decision"] == "approved" and not value["approved_evidence_level"]:
            raise SystemExit(f"{path.name}: approved decision requires approved_evidence_level")
        if value["decision"] == "approved" and not value["approved_scope"]:
            raise SystemExit(f"{path.name}: approved decision requires approved_scope")
        if value["decision"] == "approved" and (
            EVIDENCE_LEVELS[value["approved_evidence_level"]]
            > EVIDENCE_LEVELS[value["assessed_evidence_level"]]
        ):
            raise SystemExit(f"{path.name}: approved evidence level exceeds assessed evidence level")
        if value["decision"] != "approved" and value["approved_evidence_level"] is not None:
            raise SystemExit(f"{path.name}: non-approved decision cannot set approved_evidence_level")
        if value["decision"] != "approved" and value["approved_scope"] is not None:
            raise SystemExit(f"{path.name}: non-approved decision cannot set approved_scope")
        if value["decision"] is not None and not value["approver"]:
            raise SystemExit(f"{path.name}: decision requires approver")
        if value["decision"] is not None and not value["decided_at"]:
            raise SystemExit(f"{path.name}: decision requires decided_at")
        if value["review_status"] == "agent_assessed" and value["decision"] is None:
            raise SystemExit(f"{path.name}: agent_assessed review requires a decision")
        reviewed.append({"path": path.name, "decision": value["decision"]})
    print(json.dumps({"status": "valid", "reviews": reviewed}, sort_keys=True))


if __name__ == "__main__":
    main()
