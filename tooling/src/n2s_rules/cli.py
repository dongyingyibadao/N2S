import argparse
import json
import sys
from pathlib import Path

from .engine import EngineError, apply_plan, create_plan, inspect_project, rollback_report
from .paths import default_rules_root
from .plugins import PluginError
from .registry import RegistryError, validate_registry


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parser():
    parser = argparse.ArgumentParser(prog="n2s-rules", description="Fail-closed N2S migration rule runner")
    parser.add_argument("--rules-root", default=str(default_rules_root()), help="path to N2S/rules")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-registry", help="validate manifests, plugins, fixtures and registry")
    validate.add_argument("--write", action="store_true", help="write the deterministic registry after validation")

    inspect = subparsers.add_parser("inspect", help="read-only scan of Python files")
    inspect.add_argument("--project", required=True)
    inspect.add_argument("--rule", action="append", dest="rules")
    inspect.add_argument("--status", action="append", choices=["principle", "candidate", "approved"])
    inspect.add_argument("--output")

    plan = subparsers.add_parser("plan", help="build a hash-pinned transformation plan")
    plan.add_argument("--project", required=True)
    plan.add_argument("--rule", action="append", dest="rules")
    plan.add_argument("--include-candidates", action="store_true", help="include review-only candidate changes")
    plan.add_argument("--output", required=True)

    apply = subparsers.add_parser("apply", help="apply exactly one approved rule transactionally")
    apply.add_argument("--plan", required=True)
    apply.add_argument("--report")

    rollback = subparsers.add_parser("rollback", help="restore an applied report when files are unchanged")
    rollback.add_argument("--report", required=True)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    rules_root = Path(args.rules_root).resolve()
    try:
        if args.command == "validate-registry":
            registry, _ = validate_registry(rules_root, write=args.write)
            print(json.dumps({"status": "valid", "approved_rule_count": registry["approved_rule_count"], "rule_count": len(registry["rules"])}, ensure_ascii=False))
            return 0

        _, packages = validate_registry(rules_root)
        if args.command == "inspect":
            statuses = set(args.status) if args.status else None
            result = inspect_project(args.project, packages, rule_ids=args.rules, statuses=statuses)
            if args.output:
                _write_json(args.output, result)
                print(json.dumps({"output": str(Path(args.output).resolve()), "findings": len(result["findings"]), "scan_errors": len(result["scan_errors"])}, ensure_ascii=False))
            else:
                print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        if args.command == "plan":
            result = create_plan(args.project, rules_root, packages, rule_ids=args.rules, include_candidates=args.include_candidates)
            _write_json(args.output, result)
            print(json.dumps({"output": str(Path(args.output).resolve()), "changes": len(result["changes"]), "eligible": sum(change["eligible_for_apply"] for change in result["changes"])}, ensure_ascii=False))
            return 0
        if args.command == "apply":
            report, report_path = apply_plan(args.plan, packages, rules_root, report_path=args.report)
            print(json.dumps({"status": report["status"], "report": str(report_path), "files": len(report["files"])}, ensure_ascii=False))
            return 0
        if args.command == "rollback":
            report = rollback_report(args.report)
            print(json.dumps({"status": report["status"], "report": str(Path(args.report).resolve()), "files": len(report["files"])}, ensure_ascii=False))
            return 0
    except (EngineError, PluginError, RegistryError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
