import argparse
import json
import subprocess
import sys

import jsonschema

from .manager import ROOT, ExperimentError, Experiments


def parser():
    result = argparse.ArgumentParser(prog="n2s-experiments", description="Case-only, explicitly authorized experiments")
    result.add_argument("--root", default=str(ROOT))
    subs = result.add_subparsers(dest="command", required=True)
    probe = subs.add_parser("probe", help="read-only environment discovery; no model execution")
    probe.add_argument("--python", default=sys.executable)
    new = subs.add_parser("new", help="create an unverified case and draft task")
    for flag in ("id", "project", "title", "goal", "source-url"):
        new.add_argument("--" + flag, required=True)
    new.add_argument("--backend", choices=["cpu", "cuda", "npu"], default="npu")
    new.add_argument("--task-type", choices=["model_migration", "module_validation", "optimization_investigation", "tooling"],
                     help="explicit completion scope; omitted means the original full NPU migration standard")
    new.add_argument("--optimization-goal", choices=["required_gain", "investigate", "not_applicable"],
                     help="default: required_gain for model migration, investigate for optimization, otherwise not_applicable")
    new.add_argument("--model", action="append", required=True, dest="models", help="model name; repeat for related models")
    queue = subs.add_parser("list", help="show a hardware view of the shared task store")
    queue.add_argument("--backend", choices=["auto", "cpu", "cuda", "npu"], default="auto")
    queue.add_argument("--python", default=sys.executable)
    queue.add_argument("--model", help="filter by case model name, case-insensitive")
    plan = subs.add_parser("plan", help="freeze the command, source, environment and resource request")
    plan.add_argument("--task", required=True)
    plan.add_argument("--project", required=True)
    plan.add_argument("--python", default=sys.executable)
    run = subs.add_parser("run", help="execute one reviewed local plan with single-use approval")
    run.add_argument("--plan", required=True)
    run.add_argument("--approve", required=True)
    run.add_argument("--repeat-reason")
    record = subs.add_parser("record", help="append a sanitized manual observation or measurement report")
    for flag in ("task", "project", "summary", "evidence"):
        record.add_argument("--" + flag, required=True)
    record.add_argument("--outcome", required=True, choices=["reported_pass", "reported_failure", "blocked"])
    record.add_argument("--confirm-sanitized", action="store_true")
    record.add_argument("--python", default=sys.executable)
    attach = subs.add_parser("attach", help="append a sanitized report without rewriting the original run")
    for flag in ("run", "evidence", "summary"):
        attach.add_argument("--" + flag, required=True)
    attach.add_argument("--confirm-sanitized", action="store_true")
    review = subs.add_parser("review", help="review a task result, never promote a rule")
    for flag in ("run", "reviewer", "summary"):
        review.add_argument("--" + flag, required=True)
    review.add_argument("--conclusion", required=True, choices=["meets_task_acceptance", "does_not_meet", "inconclusive"])
    feedback = subs.add_parser("feedback", help="append an immediate source comparison, error or numerical observation; no probe/execution")
    feedback.add_argument("--case", required=True)
    feedback.add_argument("--file", required=True, help="sanitized JSON matching feedback.schema.json; '-' reads stdin")
    feedback.add_argument("--confirm-sanitized", action="store_true")
    draft = subs.add_parser("feedback-draft", help="generate an explicitly unread lookup draft from search metadata; no case writes")
    draft.add_argument("--case", required=True)
    draft.add_argument("--stage", choices=["preparation", "troubleshooting", "optimization"], default="preparation")
    draft.add_argument("--search-results", help="knowledge search/guide JSON; '-' reads stdin")
    draft.add_argument("--query", action="append", dest="queries")
    draft.add_argument("--resolves", action="append", default=[])
    draft.add_argument("--issue-scope", choices=["target", "tooling", "recordkeeping"],
                       help="default: tooling for a tooling case, otherwise target")
    draft.add_argument("--limit", type=int, default=8)
    preflight = subs.add_parser("feedback-preflight", help="check feedback fields, citations and evidence without writing")
    preflight.add_argument("--case", required=True)
    preflight.add_argument("--file", required=True, help="feedback JSON; '-' reads stdin")
    workflow = subs.add_parser("workflow-check", help="check three-stage lookup and migration/optimization completion evidence")
    workflow.add_argument("--case", required=True)
    validate = subs.add_parser("validate")
    validate.add_argument("--case")
    publish = subs.add_parser("publish-check", help="validate case-only staged paths; no commit or push")
    publish.add_argument("--case", required=True)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    manager = Experiments(args.root)
    try:
        if args.command == "probe":
            value = manager.probe(args.python)
        elif args.command == "new":
            value = manager.new_case(args.id, args.project, args.title, args.goal, args.source_url, args.backend, args.models,
                                     args.task_type, args.optimization_goal)
        elif args.command == "list":
            value = manager.queue(args.backend, args.python, args.model)
        elif args.command == "plan":
            value = manager.plan(args.task, args.project, args.python)
        elif args.command == "run":
            value = manager.run(args.plan, args.approve, args.repeat_reason)
        elif args.command == "record":
            value = manager.record(args.task, args.project, args.outcome, args.summary, args.evidence, args.confirm_sanitized, args.python)
        elif args.command == "attach":
            value = manager.attach(args.run, args.evidence, args.summary, args.confirm_sanitized)
        elif args.command == "review":
            value = manager.review(args.run, args.reviewer, args.conclusion, args.summary)
        elif args.command == "validate":
            value = manager.validate(args.case)
        elif args.command == "feedback":
            value = manager.feedback(args.case, args.file, args.confirm_sanitized)
        elif args.command == "feedback-draft":
            if args.limit < 1 or args.limit > 200:
                raise ExperimentError("--limit must be between 1 and 200")
            from .manager import read_json
            payload = read_json(args.search_results) if args.search_results else None
            value = manager.feedback_draft(args.case, args.stage, payload, args.queries, args.resolves, args.issue_scope, args.limit)
        elif args.command == "feedback-preflight":
            value = manager.feedback_preflight(args.case, args.file)
        elif args.command == "workflow-check":
            value = manager.workflow_check(args.case)
        else:
            value = manager.publish_check(args.case)
        print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
        if args.command == "run" and value["status"] != "command_succeeded":
            return 1
        if args.command == "workflow-check" and not value["completion_ready"]:
            return 1
        return 0
    except jsonschema.ValidationError as error:
        path = "$" + "".join("[" + str(part) + "]" if isinstance(part, int) else "." + part for part in error.absolute_path)
        if error.validator == "enum":
            detail = "allowed values: " + ", ".join(str(value) for value in error.validator_value)
        elif error.validator == "required":
            missing = [key for key in error.validator_value if key not in error.instance]
            detail = "missing required field(s): " + ", ".join(missing)
        elif error.validator == "additionalProperties":
            detail = "unknown field; check the feedback/schema fields"
        elif error.validator == "type":
            detail = "expected type: " + str(error.validator_value)
        else:
            detail = "invalid " + str(error.validator) + "; see evaluations/schemas"
        print(f"error: {path}: {detail}", file=sys.stderr)
        return 2
    except (ExperimentError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
