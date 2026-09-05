import argparse
import json
import sys

from .manager import KnowledgeError, KnowledgeManager
from .paths import default_n2s_root


def _parser():
    parser = argparse.ArgumentParser(
        prog="n2s-knowledge",
        description="Synchronize and query version-pinned official upstream knowledge without executing it",
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
    search.add_argument("--json", action="store_true")

    show = subparsers.add_parser("show", help="display an exact upstream snapshot file")
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


def _print_search(report):
    for item in report["results"]:
        print(f"[{item['trust']}] {item['title']}")
        print(f"  {item['source']}@{item['revision']} {item['path']}")
        print(f"  {item['uri']}")
        print(f"  local: {item['local_path'] or '-'}")
        print(f"  remote: {item['remote_url']}")
        if item["excerpt"]:
            print(f"  {item['excerpt']}")


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
            report = manager.search(args.query, scope=args.scope, accepted_only=args.accepted_only)
            if args.json:
                print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
            else:
                _print_search(report)
            return 0
        if args.command == "show":
            result = manager.show(args.uri)
            if result["content"] is None:
                print("snapshot file is not available locally", file=sys.stderr)
                print(f"fixed remote: {result['remote_url']}", file=sys.stderr)
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
    except KnowledgeError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
