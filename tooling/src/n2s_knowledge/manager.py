import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import jsonschema

from .indexer import IndexError, build_index, deterministic_json, list_tree, read_object


class KnowledgeError(RuntimeError):
    pass


def _now():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def _timestamp(value=None):
    return (value or _now()).isoformat().replace("+00:00", "Z")


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise KnowledgeError(f"cannot read JSON {path}: {error}") from error


def _atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(deterministic_json(value), encoding="utf-8")
    os.replace(temporary, path)


def _validate(value, schema_path, label):
    schema = _read_json(schema_path)
    try:
        jsonschema.Draft202012Validator(schema).validate(value)
    except jsonschema.ValidationError as error:
        location = "/".join(str(part) for part in error.absolute_path) or "<root>"
        raise KnowledgeError(f"invalid {label} at {location}: {error.message}") from error


def _is_license_path(path):
    name = PurePosixPath(path).name.casefold()
    return (
        name.startswith("license")
        or name.startswith("copying")
        or "notice" in name
        or name in {"disclaimer", "disclaimer.md"}
    )


class KnowledgeManager:
    def __init__(self, root, now=None):
        self.root = Path(root).resolve()
        self.upstreams_root = self.root / "upstreams"
        self.cache_root = self.upstreams_root / "_cache"
        self.sources_path = self.upstreams_root / "sources.json"
        self.schemas_root = self.upstreams_root / "schemas"
        self.state_path = self.cache_root / "state.json"
        self.lock_path = self.cache_root / "sync.lock"
        self.now = now or _now
        self.registry = _read_json(self.sources_path)
        _validate(self.registry, self.schemas_root / "source.schema.json", "source registry")
        self.sources = {source["id"]: source for source in self.registry["sources"]}

    def _source(self, source_id=None):
        if source_id is None:
            if len(self.sources) != 1:
                raise KnowledgeError("--source is required when multiple upstreams are registered")
            return next(iter(self.sources.values()))
        try:
            return self.sources[source_id]
        except KeyError as error:
            raise KnowledgeError(f"unknown upstream source: {source_id}") from error

    def _source_cache(self, source):
        return self.cache_root / source["id"]

    def _mirror(self, source):
        return self._source_cache(source) / "mirror.git"

    def _snapshot(self, source, revision):
        return self._source_cache(source) / "snapshots" / revision

    def _live_index_path(self, source):
        return self._source_cache(source) / "live-index.json"

    def _load_state(self):
        if not self.state_path.exists():
            return {"schema_version": "1.0.0", "sources": {}}
        state = _read_json(self.state_path)
        if not isinstance(state.get("sources"), dict):
            raise KnowledgeError(f"invalid sync state: {self.state_path}")
        return state

    def _write_state(self, state):
        _atomic_json(self.state_path, state)

    @contextlib.contextmanager
    def _lock(self):
        self.cache_root.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def _git(self, source, *args, check=True):
        mirror = self._mirror(source)
        command = ["git", "-c", "core.hooksPath=/dev/null"]
        if mirror.exists():
            command.append(f"--git-dir={mirror}")
        command.extend(args)
        environment = os.environ.copy()
        environment.update({"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"})
        result = subprocess.run(command, capture_output=True, text=True, env=environment)
        if check and result.returncode:
            detail = result.stderr.strip() or result.stdout.strip() or "git command failed"
            raise KnowledgeError(detail)
        return result

    def _ensure_mirror(self, source):
        mirror = self._mirror(source)
        mirror.parent.mkdir(parents=True, exist_ok=True)
        if mirror.exists():
            return False
        temporary = mirror.with_name(f".mirror.git.tmp-{os.getpid()}")
        if temporary.exists():
            shutil.rmtree(temporary)
        command = [
            "git", "-c", "core.hooksPath=/dev/null", "clone", "--mirror",
            source["remote_url"], str(temporary),
        ]
        environment = os.environ.copy()
        environment.update({"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"})
        try:
            result = subprocess.run(command, capture_output=True, text=True, env=environment)
            if result.returncode:
                raise KnowledgeError(result.stderr.strip() or "failed to clone upstream mirror")
            os.replace(temporary, mirror)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
        return True

    def _resolve(self, source, revision):
        result = self._git(source, "rev-parse", f"{revision}^{{commit}}")
        return result.stdout.strip()

    def _license_fingerprints(self, source, revision):
        fingerprints = {}
        for entry in list_tree(self._mirror(source), revision):
            if entry["git_object_type"] == "blob" and _is_license_path(entry["path"]):
                content = read_object(self._mirror(source), entry["git_object_id"])
                fingerprints[entry["path"]] = hashlib.sha256(content).hexdigest()
        return fingerprints

    def _materialize(self, source, revision):
        revision = self._resolve(source, revision)
        destination = self._snapshot(source, revision)
        if destination.is_dir():
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{revision}.tmp-{os.getpid()}")
        if temporary.exists():
            shutil.rmtree(temporary)
        temporary.mkdir()
        try:
            for entry in list_tree(self._mirror(source), revision):
                target = temporary / entry["path"]
                if entry["git_object_type"] == "commit":
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                content = read_object(self._mirror(source), entry["git_object_id"])
                if entry["mode"] == "120000":
                    link_target = content.decode("utf-8", "surrogateescape")
                    resolved = (target.parent / link_target).resolve()
                    if os.path.commonpath([resolved, temporary.resolve()]) == str(temporary.resolve()):
                        target.symlink_to(link_target)
                    else:
                        target.write_bytes(content)
                else:
                    target.write_bytes(content)
                    target.chmod(0o555 if entry["mode"] == "100755" else 0o444)
            for directory in sorted((item for item in temporary.rglob("*") if item.is_dir()), reverse=True):
                directory.chmod(0o555)
            temporary.chmod(0o555)
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                for directory, dirs, files in os.walk(temporary, topdown=False):
                    for name in files:
                        path = Path(directory) / name
                        if not path.is_symlink():
                            path.chmod(stat.S_IWUSR | stat.S_IRUSR)
                    Path(directory).chmod(0o700)
                shutil.rmtree(temporary)
        return destination

    def _switch_current(self, source, revision):
        source_cache = self._source_cache(source)
        current = source_cache / "current"
        temporary = source_cache / f".current.tmp-{os.getpid()}"
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()
        temporary.symlink_to(Path("snapshots") / revision)
        os.replace(temporary, current)

    def _build_live(self, source, revision):
        index = build_index(self._mirror(source), source, revision)
        _validate(index, self.schemas_root / "index.schema.json", "live index")
        _atomic_json(self._live_index_path(source), index)
        return index

    def refresh(self, force=False, source_id=None):
        source = self._source(source_id)
        with self._lock():
            state = self._load_state()
            source_state = state["sources"].setdefault(source["id"], {})
            now = self.now()
            today = now.date().isoformat()
            if not force and source_state.get("last_attempt_date") == today:
                return {"action": "skipped_already_attempted", "source": source["id"], **source_state}

            source_state.update(
                {
                    "accepted_revision": source["accepted_revision"],
                    "last_attempt_at": _timestamp(now),
                    "last_attempt_date": today,
                }
            )
            self._write_state(state)
            previous_current = source_state.get("current_revision")
            try:
                created = self._ensure_mirror(source)
                mirror_url = self._git(source, "config", "--get", "remote.origin.url").stdout.strip()
                url_changed = mirror_url != source["remote_url"]
                if created:
                    latest = self._resolve(source, f"refs/heads/{source['branch']}")
                elif url_changed:
                    self._git(source, "fetch", source["remote_url"], f"refs/heads/{source['branch']}")
                    latest = self._resolve(source, "FETCH_HEAD")
                else:
                    self._git(source, "fetch", "--prune", "origin")
                    latest = self._resolve(source, f"refs/heads/{source['branch']}")

                accepted = self._resolve(source, source["accepted_revision"])
                if previous_current:
                    current = self._resolve(source, previous_current)
                else:
                    current = accepted
                    self._materialize(source, current)
                    self._switch_current(source, current)
                    self._build_live(source, current)

                blocked_reason = None
                if url_changed:
                    blocked_reason = "remote_url_changed"
                elif self._git(source, "merge-base", "--is-ancestor", current, latest, check=False).returncode:
                    blocked_reason = "history_rewrite"
                elif self._license_fingerprints(source, current) != self._license_fingerprints(source, latest):
                    blocked_reason = "license_changed"

                if blocked_reason:
                    selected = current
                    action = f"blocked_{blocked_reason}"
                else:
                    selected = latest
                    self._materialize(source, selected)
                    self._switch_current(source, selected)
                    self._build_live(source, selected)
                    action = "current" if selected == accepted else "unreviewed_update"

                source_state.update(
                    {
                        "current_revision": selected,
                        "last_error": None,
                        "last_success_at": _timestamp(now),
                        "license_warning": blocked_reason == "license_changed",
                        "observed_remote_url": source["remote_url"],
                        "remote_latest_revision": latest,
                        "stale": False,
                        "update_status": action,
                    }
                )
                self._write_state(state)
                return {"action": action, "source": source["id"], **source_state}
            except (KnowledgeError, IndexError, OSError) as error:
                source_state.update(
                    {
                        "last_error": str(error),
                        "stale": bool(previous_current or source_state.get("current_revision")),
                        "update_status": "offline_fallback" if (previous_current or source_state.get("current_revision")) else "unavailable",
                    }
                )
                self._write_state(state)
                return {"action": source_state["update_status"], "source": source["id"], **source_state}

    def status(self):
        state = self._load_state()
        results = []
        for source in self.sources.values():
            cached = state["sources"].get(source["id"], {})
            results.append(
                {
                    "accepted_revision": source["accepted_revision"],
                    "current_revision": cached.get("current_revision"),
                    "last_attempt_at": cached.get("last_attempt_at"),
                    "last_error": cached.get("last_error"),
                    "last_success_at": cached.get("last_success_at"),
                    "license_warning": cached.get("license_warning", False),
                    "remote_latest_revision": cached.get("remote_latest_revision"),
                    "source": source["id"],
                    "stale": cached.get("stale", False),
                    "update_status": cached.get("update_status", "not_initialized"),
                    "usage_warning": source["usage_restrictions"],
                }
            )
        return {"schema_version": "1.0.0", "sources": results}

    def _resolve_alias(self, source, revision):
        if revision == "accepted":
            return source["accepted_revision"]
        if revision == "live":
            state = self._load_state()["sources"].get(source["id"], {})
            if not state.get("current_revision"):
                raise KnowledgeError(f"no live snapshot for {source['id']}; run refresh-if-due")
            return state["current_revision"]
        if not re.fullmatch(r"[0-9a-fA-F]{7,40}", revision):
            raise KnowledgeError(f"revision must be a Git SHA or accepted/live: {revision}")
        mirror = self._mirror(source)
        if mirror.exists():
            return self._resolve(source, revision)
        if len(revision) != 40:
            raise KnowledgeError("an uncached revision must be a full 40-character SHA")
        return revision.lower()

    def show(self, uri):
        match = re.fullmatch(r"upstream://([^@/]+)@([^/]+)/(.+)", uri)
        if not match:
            raise KnowledgeError("expected upstream://SOURCE@REVISION/PATH")
        source = self._source(match.group(1))
        revision = self._resolve_alias(source, match.group(2))
        path = PurePosixPath(match.group(3))
        if path.is_absolute() or ".." in path.parts:
            raise KnowledgeError("unsafe upstream path")
        local = self._snapshot(source, revision) / str(path)
        remote = source["browse_url_template"].format(revision=revision, path=quote(str(path), safe="/"))
        if local.is_file():
            return {"content": local.read_bytes(), "local_path": str(local), "remote_url": remote, "revision": revision}
        return {"content": None, "local_path": None, "remote_url": remote, "revision": revision}

    def _knowledge(self):
        items = []
        for path in sorted((self.upstreams_root / "knowledge").glob("*.json")):
            catalog = _read_json(path)
            _validate(catalog, self.schemas_root / "knowledge.schema.json", f"knowledge catalog {path.name}")
            items.extend(catalog["items"])
        return items

    def search(self, query, scope=None, accepted_only=False):
        terms = [term.casefold() for term in query.split() if term]
        if not terms:
            raise KnowledgeError("search query cannot be empty")
        results = []
        for item in self._knowledge():
            if scope and scope not in item["scope"]:
                continue
            reference = item["official_claim"]["references"][0]
            source = self._source(reference["source"])
            if accepted_only and reference["revision"] != source["accepted_revision"]:
                continue
            haystack = deterministic_json(item).casefold()
            if all(term in haystack for term in terms):
                revision = reference["revision"]
                path = reference["path"]
                snapshot_path = self._snapshot(source, revision) / path
                results.append(
                    self._search_result(
                        source, revision, path, item["title"], item["official_claim"]["summary"],
                        "curated_knowledge", snapshot_path, item["type"],
                    )
                )

        for source in self.sources.values():
            state = self._load_state()["sources"].get(source["id"], {})
            revision = source["accepted_revision"] if accepted_only else state.get("current_revision", source["accepted_revision"])
            index_path = self.upstreams_root / "indexes" / f"{source['id']}.json" if accepted_only else self._live_index_path(source)
            if not index_path.exists():
                index_path = self.upstreams_root / "indexes" / f"{source['id']}.json"
            index = _read_json(index_path)
            revision = index["revision"]
            snapshot = self._snapshot(source, revision)
            for entry in index["files"]:
                path = entry["path"]
                if scope and not (path.startswith(f"{scope}/") or path.startswith(f"docs/{scope}/")):
                    continue
                local = snapshot / path
                candidate = f"{path}\n{entry.get('title') or ''}"
                body = ""
                if local.is_file() and not local.is_symlink() and entry["type"] != "binary":
                    body = local.read_text(encoding="utf-8", errors="replace")
                combined = f"{candidate}\n{body}".casefold()
                if all(term in combined for term in terms):
                    excerpt = self._excerpt(body or candidate, terms)
                    results.append(
                        self._search_result(
                            source, revision, path, entry.get("title") or path, excerpt,
                            "official_fulltext", local, entry["type"],
                        )
                    )
        results.sort(key=lambda item: (item["result_kind"], item["source"], item["path"], item["title"]))
        return {"query": query, "results": results[:200], "scope": scope}

    def _excerpt(self, body, terms):
        lines = body.splitlines()
        for line in lines:
            folded = line.casefold()
            if all(term in folded for term in terms):
                return line.strip()[:500]
        for line in lines:
            if any(term in line.casefold() for term in terms):
                return line.strip()[:500]
        return ""

    def _search_result(self, source, revision, path, title, excerpt, result_kind, local, entry_type):
        accepted = source["accepted_revision"]
        return {
            "entry_type": entry_type,
            "excerpt": excerpt,
            "local_path": str(local) if local.is_file() else None,
            "path": path,
            "remote_url": source["browse_url_template"].format(revision=revision, path=quote(str(path), safe="/")),
            "result_kind": result_kind,
            "revision": revision,
            "source": source["id"],
            "title": title,
            "trust": "accepted_upstream_documented" if revision == accepted else "unreviewed_latest_upstream",
            "uri": f"upstream://{source['id']}@{revision}/{path}",
        }

    def diff(self, from_revision="accepted", to_revision="live", source_id=None):
        source = self._source(source_id)
        if not self._mirror(source).exists():
            raise KnowledgeError("upstream mirror is missing; run refresh-if-due")
        old = self._resolve_alias(source, from_revision)
        new = self._resolve_alias(source, to_revision)
        log = self._git(source, "log", "--format=%H%x09%s", f"{old}..{new}").stdout.splitlines()
        raw_changes = self._git(source, "diff", "--name-status", old, new).stdout.splitlines()
        changes = []
        high_attention = []
        for line in raw_changes:
            fields = line.split("\t")
            record = {"status": fields[0], "paths": fields[1:]}
            changes.append(record)
            for path in fields[1:]:
                category = self._attention_category(path)
                if category:
                    high_attention.append({"category": category, "path": path})
        changed_paths = {path for change in changes for path in change["paths"]}
        affected = []
        for item in self._knowledge():
            references = item["official_claim"]["references"]
            if any(reference["source"] == source["id"] and reference["path"] in changed_paths for reference in references):
                affected.append({"id": item["id"], "title": item["title"], "type": item["type"]})
        return {
            "affected_knowledge": affected,
            "commits": [{"revision": line.split("\t", 1)[0], "subject": line.split("\t", 1)[1]} for line in log],
            "from": old,
            "high_attention": high_attention,
            "paths": changes,
            "source": source["id"],
            "to": new,
        }

    def _attention_category(self, path):
        folded = path.casefold()
        if _is_license_path(path):
            return "license"
        if folded.endswith(".patch"):
            return "patch"
        if folded.endswith(("requirements.txt", "pyproject.toml", ".yaml", ".yml", ".json")):
            return "configuration_or_version"
        if folded.endswith(("readme.md", ".rst")) or folded.startswith("docs/"):
            return "documentation_or_validation"
        return None

    def accept(self, source_id, revision, review_path):
        source = self._source(source_id)
        if not self._mirror(source).exists():
            raise KnowledgeError("upstream mirror is missing; run sync --force first")
        resolved = self._resolve(source, revision)
        review = _read_json(review_path)
        _validate(review, self.schemas_root / "review.schema.json", "acceptance review")
        if review["source"] != source_id or self._resolve(source, review["revision"]) != resolved:
            raise KnowledgeError("review source/revision does not match the requested acceptance")
        if review["remote_url"] != source["remote_url"]:
            raise KnowledgeError("review remote_url does not match the registered source")
        if review["decision"] != "accept" or not review["license_checked"]:
            raise KnowledgeError("review must explicitly accept the revision and confirm license review")
        with self._lock():
            updated = _read_json(self.sources_path)
            selected = next(item for item in updated["sources"] if item["id"] == source_id)
            selected["accepted_revision"] = resolved
            selected["accepted_license_fingerprints"] = self._license_fingerprints(source, resolved)
            review_name = f"{review['reviewed_at'][:10]}-{source_id}-{resolved[:12]}.json"
            recorded_review = self.upstreams_root / "reviews" / review_name
            _atomic_json(recorded_review, review)
            selected["acceptance_review"] = f"upstreams/reviews/{review_name}"
            _validate(updated, self.schemas_root / "source.schema.json", "updated source registry")
            index = build_index(self._mirror(source), selected, resolved)
            _validate(index, self.schemas_root / "index.schema.json", "accepted index")
            mirror_url = self._git(source, "config", "--get", "remote.origin.url").stdout.strip()
            if mirror_url != selected["remote_url"]:
                self._git(source, "remote", "set-url", "origin", selected["remote_url"])
            self._materialize(source, resolved)
            self._switch_current(source, resolved)
            _atomic_json(self._live_index_path(source), index)
            _atomic_json(self.upstreams_root / "indexes" / f"{source_id}.json", index)
            _atomic_json(self.sources_path, updated)
            self.registry = updated
            self.sources = {item["id"]: item for item in updated["sources"]}
            state = self._load_state()
            source_state = state["sources"].setdefault(source_id, {})
            source_state.update(
                {
                    "accepted_revision": resolved,
                    "current_revision": resolved,
                    "last_error": None,
                    "license_warning": False,
                    "stale": False,
                    "update_status": "current",
                }
            )
            self._write_state(state)
        return {"accepted_revision": resolved, "index_files": len(index["files"]), "review": str(recorded_review)}
