#!/usr/bin/env python3
import json
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parent


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
