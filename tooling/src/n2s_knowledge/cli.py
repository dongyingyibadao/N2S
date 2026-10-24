import argparse
import json
import sys

from .context import ContextError, load_target_profile
from .manager import KnowledgeError, KnowledgeManager
from .paths import default_n2s_root
from .references import ReferenceError, ReferenceLibrary


TASKS = ["environment", "training", "inference", "distributed", "memory", "numerics", "performance", "simulation", "data"]
STAGES = ["preparation", "troubleshooting", "optimization"]


def _parser():
    parser = argparse.ArgumentParser(
        prog="n2s-knowledge",
        description="Query official snapshots, community references and migration source links without executing them",
    )
    parser.add_argument("--root", default=str(default_n2s_root()), help="path to the N2S repository")
    subparsers = parser.add_subparsers(dest="command", required=True)

    refresh = subparsers.add_parser("refresh-if-due", help="check each UTC day at most once")
    refresh.add_argument("--source")

    sync = subparsers.add_parser("sync", help="check the remote upstream")
    sync.add_argument("--force", action="store_true", help="ignore the daily attempt limit")
    sync.add_argument("--source")

    status = subparsers.add_parser("status", help="show accepted, remote and local snapshot state")
    status.add_argument("--json", action="store_true")

    search = subparsers.add_parser("search", help="search curated knowledge and official full text")
    search.add_argument("query")
    search.add_argument("--scope")
    search.add_argument("--accepted-only", action="store_true")
    search.add_argument("--include-community", action="store_true", help="also search pinned, selected LeRobot/OpenPI source snapshots")
    search.add_argument("--task", choices=TASKS, help="route reference-bundle results by task; official text remains searchable")
    search.add_argument("--stage", choices=STAGES, help="route reference-bundle results by migration stage")
    search.add_argument("--target-profile", help="read explicit target JSON for soft ordering and documented differences; no project/device probing")
    search.add_argument("--json", action="store_true")

    guide = subparsers.add_parser("guide", help="list relevant reference summaries, source links and limitations")
    guide.add_argument("--task", choices=TASKS, required=True)
    guide.add_argument("--stage", choices=STAGES)
    guide.add_argument("--target-profile", help="read explicit target JSON for soft ordering; missing metadata remains unknown")
    guide.add_argument("--json", action="store_true")

    bundle = subparsers.add_parser("import-bundle", help="verify and cache a registered reference bundle as read-only data")
    bundle.add_argument("--source", required=True)
    bundle.add_argument("--path", required=True, help="extracted directory containing the registered checksum manifest")

    follow = subparsers.add_parser("follow", help="read a cataloged HTTPS link without executing its content")
    follow.add_argument("url")
    follow.add_argument("--from-url", action="append", default=[], metavar="PARENT",
                        help="verify an actual child link; repeat in order from a catalog root through intermediate parents")

    show = subparsers.add_parser("show", help="display an exact official, community or reference-bundle snapshot file")
    show.add_argument("uri")

    difference = subparsers.add_parser("diff", help="review upstream commits, paths and affected knowledge")
    difference.add_argument("--source")
    difference.add_argument("--from", dest="from_revision", default="accepted")
    difference.add_argument("--to", dest="to_revision", default="live")

    accept = subparsers.add_parser("accept", help="accept a reviewed revision and rebuild its deterministic index")
    accept.add_argument("--source", required=True)
    accept.add_argument("--revision", required=True)
    accept.add_argument("--review", required=True)
    return parser


def _print_refresh(result):
    print(f"source: {result.get('source', 'configured upstream')}")
    print(f"action: {result['action']}")
    print(f"accepted: {result.get('accepted_revision') or '-'}")
    print(f"remote latest: {result.get('remote_latest_revision') or '-'}")
    print(f"current snapshot: {result.get('current_revision') or '-'}")
    if result.get("last_error"):
        print(f"warning: {result['last_error']}")


def _print_status(report):
    for item in report["sources"]:
        print(f"{item['source']}: {item['update_status']}")
        print(f"  accepted: {item['accepted_revision']}")
        print(f"  remote latest: {item['remote_latest_revision'] or '-'}")
        print(f"  current snapshot: {item['current_revision'] or '-'}")
        print(f"  last check: {item['last_attempt_at'] or '-'}")
        if item["stale"]:
            print("  warning: offline or failed refresh; using the last successful snapshot")
        if item["license_warning"]:
            print("  warning: license files changed; automatic snapshot switching is blocked")
        print(f"  usage: {item['usage_warning']}")
    _print_reference_status(report)


def _print_reference_status(report):
    for item in report.get("reference_bundles", []):
        print(f"reference bundle {item['source']}: {item['status']} (captured {item['captured_at']})")
        if item["status"] != "available":
            print(f"  warning: {item['error'] or 'full text not imported on this host; summaries and links are available'}")


def _print_search(report):
    for item in report["results"]:
        print(f"[{item['trust']}] {item['title']}")
        print(f"  {item['source']}@{item['revision']} {item['path']}")
        print(f"  {item['uri']}")
        if item.get("coverage"):
            print(f"  coverage: {item['coverage']}")
        if item.get("n2s_validation"):
            validation = item["n2s_validation"]
            print(f"  N2S validation: {validation['status']} ({validation['level']})")
        for key in ("tasks", "models", "modes", "devices", "software_versions", "performance_context"):
            if item.get(key):
                print(f"  {key}: {json.dumps(item[key], ensure_ascii=False, sort_keys=True)}")
        if item.get("context_comparison"):
            print(f"  target context score: {item['context_score']} (ordering only; compatibility not determined)")
            for field in item["context_comparison"]["fields"]:
                print(f"  {field['field']}: {field['status']}; target={field['target']}; documented={field['documented']}; {field['reason']}")
        for relation in item.get("rule_relations", []):
            print(f"  related rule: {relation['rule_id']} ({relation['relation']})")
        print(f"  local: {item['local_path'] or '-'}")
        if item.get("trust") == "community_reference_bundle":
            print(f"  source entry (not an exact cached-file URL): {item.get('remote_url') or item.get('origin_url') or '-'}")
        else:
            print(f"  remote: {item.get('remote_url') or '-'}")
        if item["excerpt"]:
            print(f"  {item['excerpt']}")
        for key in ("evidence", "conditions", "limitations"):
            if item.get(key):
                print(f"  {key}: {item[key]}")
        for gap in item.get("uncovered_scope", []):
            print(f"  uncovered: {gap}")
        for reference in item.get("references", []):
            print(f"  reference: {reference.get('uri') or reference.get('path', '-')} [{reference.get('trust', item['trust'])}]")
            print(f"    remote: {reference.get('remote_url') or 'not provided for this exact file'}")
            if reference.get("origin_url"):
                print(f"    bundle origin (not an exact file URL): {reference['origin_url']}")
            print(f"    local: {reference.get('local_path') or '-'}")
        for link in item.get("links", []):
            print(f"  source link: {link['url']} ({link['content_status']})")
            if link.get("snapshot_uri"):
                print(f"  pinned snapshot: {link['snapshot_uri']}")
    if report.get("truncated"):
        print(f"Showing {len(report['results'])} of {report['total_results']} matches; refine the query or use guide for reference routes.")
    _print_reference_status(report)


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        manager = KnowledgeManager(args.root)
        if args.command == "refresh-if-due":
            _print_refresh(manager.refresh(force=False, source_id=args.source))
            return 0
        if args.command == "sync":
            result = manager.refresh(force=args.force, source_id=args.source)
            _print_refresh(result)
            return 1 if result["action"] in {"unavailable"} else 0
        if args.command == "status":
            report = manager.status()
            if args.json:
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                _print_status(report)
            return 0
        if args.command == "search":
            report = manager.search(args.query, scope=args.scope, accepted_only=args.accepted_only,
                                    include_community=args.include_community, task=args.task, stage=args.stage,
                                    profile=load_target_profile(args.target_profile))
            if args.json:
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                _print_search(report)
            return 0
        if args.command == "guide":
            report = ReferenceLibrary(args.root).guide(args.task, args.stage, profile=load_target_profile(args.target_profile))
            if args.json:
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                _print_search(report)
            return 0
        if args.command == "import-bundle":
            report = ReferenceLibrary(args.root).import_bundle(args.source, args.path)
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        if args.command == "follow":
            report = ReferenceLibrary(args.root).follow(args.url, from_url=args.from_url)
            print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            return 0 if report["status"] == "retrieved" else 3
        if args.command == "show":
            if args.uri.startswith("reference://"):
                result = ReferenceLibrary(args.root).show(args.uri)
            else:
                result = manager.show_community(args.uri) if args.uri.startswith("community://") else manager.show(args.uri)
            if result["content"] is None:
                print("snapshot file is not available locally", file=sys.stderr)
                print(f"source link: {result['remote_url']}", file=sys.stderr)
                if args.uri.startswith("reference://"):
                    print("import the registered bundle for this exact offline version; its web source may require login", file=sys.stderr)
                return 3
            sys.stdout.buffer.write(result["content"])
            return 0
        if args.command == "diff":
            print(
                json.dumps(
                    manager.diff(args.from_revision, args.to_revision, args.source),
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "accept":
            print(json.dumps(manager.accept(args.source, args.revision, args.review), ensure_ascii=False, sort_keys=True))
            return 0
    except (KnowledgeError, ReferenceError, ContextError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
