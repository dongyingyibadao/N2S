"""Read-only reference bundles and task-oriented, N2S-authored source catalogs."""

import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

import jsonschema


class ReferenceError(ValueError):
    pass


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ReferenceError(f"Cannot read reference metadata: {path}: {error}") from error


def checksum(content):
    return hashlib.sha256(content).hexdigest()


def safe_path(base, relative):
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts or str(path) != relative:
        raise ReferenceError(f"Unsafe reference path: {relative}")
    local = base / relative
    for parent in (local, *local.parents):
        if parent.is_symlink():
            raise ReferenceError(f"Reference symlinks are not allowed: {relative}")
        if parent == base:
            break
    if not local.resolve().is_relative_to(base.resolve()):
        raise ReferenceError(f"Reference path escapes snapshot: {relative}")
    return local


def public_url(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ReferenceError("Reference links must use HTTPS without credentials")
    return url


class _HTTPSRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, url):
        return super().redirect_request(request, response, code, message, headers, public_url(url))


class _PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1
        elif tag in {"p", "br", "div", "li", "h1", "h2", "h3", "pre"}:
            self.text.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)


class ReferenceLibrary:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.cache = self.root / "upstreams/_cache/reference-bundles"
        registry = self.root / "upstreams/reference-bundles.json"
        self.sources = {}
        self.items = []
        if not registry.exists():
            return
        value = read_json(registry)
        self.validate(value, "reference-bundles")
        for source in value["bundles"]:
            if source["id"] in self.sources:
                raise ReferenceError("Duplicate reference bundle ID")
            self.sources[source["id"]] = source
            catalog = read_json(safe_path(self.root, source["catalog"]))
            self.validate(catalog, "reference-catalog")
            for item in catalog["items"]:
                if (item["source"] != source["id"]
                        or (item["source"], item["id"]) in {(entry["source"], entry["id"]) for entry in self.items}):
                    raise ReferenceError("Reference catalog source or ID mismatch")
                for reference in item["references"]:
                    safe_path(self.snapshot(source), reference["path"])
                for link in item["links"]:
                    public_url(link["url"])
                self.items.append(item)

    def validate(self, value, kind):
        schema = read_json(self.root / f"upstreams/schemas/{kind}.schema.json")
        try:
            jsonschema.Draft202012Validator(schema).validate(value)
        except jsonschema.ValidationError as error:
            raise ReferenceError(f"Invalid {kind}: {error.message}") from error

    def source(self, source_id):
        if source_id not in self.sources:
            raise ReferenceError(f"Unknown reference bundle: {source_id}")
        return self.sources[source_id]

    def snapshot(self, source):
        return safe_path(self.root, f"upstreams/_cache/reference-bundles/{source['id']}/{source['revision']}")

    def manifest(self, source, directory):
        manifest = safe_path(directory, source["manifest_path"])
        if not manifest.is_file() or checksum(manifest.read_bytes()) != source["revision"]:
            raise ReferenceError(f"Reference manifest checksum mismatch: {source['id']}")
        value = read_json(manifest)
        self.validate(value, "reference-manifest")
        entries = value["files"] + source["extra_files"]
        files = {}
        for entry in entries:
            relative = entry["path"]
            if relative in files or relative == source["manifest_path"]:
                raise ReferenceError("Duplicate reference manifest path")
            safe_path(directory, relative)
            files[relative] = entry
        files[source["manifest_path"]] = {"path": source["manifest_path"], "sha256": source["revision"]}
        return files

    def verified_file(self, source, directory, entry):
        local = safe_path(directory, entry["path"])
        if not local.is_file():
            raise ReferenceError(f"Reference file missing: {source['id']}/{entry['path']}")
        content = local.read_bytes()
        if checksum(content) != entry["sha256"] or ("bytes" in entry and len(content) != entry["bytes"]):
            raise ReferenceError(f"Reference checksum mismatch: {source['id']}/{entry['path']}")
        return local, content

    def import_bundle(self, source_id, path):
        source = self.source(source_id)
        directory = Path(path).absolute()
        if directory.is_symlink() or not directory.is_dir():
            raise ReferenceError("Provide the extracted reference bundle directory, not a symlink")
        files = self.manifest(source, directory)
        self.cache.mkdir(parents=True, exist_ok=True)
        with (self.cache / "import.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            destination = self.snapshot(source)
            if destination.exists():
                for entry in files.values():
                    self.verified_file(source, destination, entry)
                return {"action": "already_imported", "source": source_id, "revision": source["revision"]}
            temporary = Path(tempfile.mkdtemp(prefix=".import-", dir=self.cache))
            try:
                for entry in files.values():
                    _, content = self.verified_file(source, directory, entry)
                    target = safe_path(temporary, entry["path"])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                # Retain all original bytes, screenshots, provenance and relative links as inert data.
                for target in temporary.rglob("*"):
                    target.chmod(0o555 if target.is_dir() else 0o444)
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(temporary, destination)
                destination.chmod(0o555)
            finally:
                if temporary.exists():
                    for target in temporary.rglob("*"):
                        if target.is_dir():
                            target.chmod(0o755)
                    shutil.rmtree(temporary)
        return {"action": "imported", "source": source_id, "revision": source["revision"],
                "files": len(files), "snapshot": str(destination), "trust": "community_reference_bundle"}

    def status(self):
        result = []
        for source in self.sources.values():
            snapshot = self.snapshot(source)
            status = "not_imported"
            error = None
            if snapshot.exists():
                try:
                    for entry in self.manifest(source, snapshot).values():
                        self.verified_file(source, snapshot, entry)
                    status = "available"
                except ReferenceError as exception:
                    status, error = "invalid", str(exception)
            result.append({"source": source["id"], "revision": source["revision"], "status": status,
                           "captured_at": source["captured_at"], "trust": "community_reference_bundle",
                           "error": error, "missing_sources": source["missing_sources"],
                           "usage_warning": source["usage_restrictions"]})
        return result

    def selected(self, task=None, stage=None, scope=None):
        return [item for item in self.items if (not task or task in item["tasks"])
                and (not stage or stage in item["stages"])
                and (not scope or scope in item["scopes"] or "general" in item["scopes"])]

    def result(self, item):
        source = self.source(item["source"])
        path = item["references"][0]["path"]
        snapshot = self.snapshot(source)
        files = self.manifest(source, snapshot) if snapshot.exists() else {}
        references = []
        for reference in item["references"]:
            relative = reference["path"]
            local = None
            content_sha256 = None
            if snapshot.exists():
                if relative not in files:
                    raise ReferenceError(f"Catalog reference absent from manifest: {relative}")
                local, _ = self.verified_file(source, snapshot, files[relative])
                content_sha256 = files[relative]["sha256"]
            references.append({**reference, "uri": f"reference://{source['id']}@{source['revision']}/{relative}",
                               "local_path": str(local) if local else None, "content_sha256": content_sha256})
        return {**item, "references": references, "entry_type": "reference_summary", "excerpt": item["summary"],
                "result_kind": "reference_catalog", "revision": source["revision"],
                "revision_kind": "bundle_manifest_sha256", "path": path,
                "trust": "community_reference_bundle", "n2s_validation": {"status": "not_verified", "level": "not_verified"},
                "uri": f"reference://{source['id']}@{source['revision']}/{path}",
                "local_path": references[0]["local_path"], "content_sha256": references[0]["content_sha256"],
                "remote_url": item["links"][0]["url"] if item["links"] else source["origin_url"],
                "coverage": source["coverage"]}

    def guide(self, task, stage=None):
        return {"task": task, "stage": stage, "results": [self.result(item) for item in self.selected(task, stage)],
                "reference_bundles": self.status()}

    def search(self, terms, task=None, stage=None, scope=None):
        selected = self.selected(task, stage, scope)
        results = [self.result(item) for item in selected
                   if all(term in json.dumps(item, ensure_ascii=False).casefold() for term in terms)]
        allowed = {(item["source"], ref["path"]) for item in selected for ref in item["references"]}
        for source in self.sources.values():
            snapshot = self.snapshot(source)
            if not snapshot.exists():
                continue
            for entry in self.manifest(source, snapshot).values():
                local, content = self.verified_file(source, snapshot, entry)
                if local.suffix not in {".md", ".txt", ".bashrc"}:
                    continue
                if (task or stage or scope) and (source["id"], entry["path"]) not in allowed:
                    continue
                body = content.decode("utf-8", errors="replace")
                if not all(term in f"{entry['path']}\n{body}".casefold() for term in terms):
                    continue
                matching = [item for item in selected if item["source"] == source["id"]
                            and entry["path"] in {ref["path"] for ref in item["references"]}]
                matched_catalog = [item for item in matching
                                   if all(term in json.dumps(item, ensure_ascii=False).casefold() for term in terms)]
                links = []
                for item in matched_catalog or matching:
                    for link in item["links"]:
                        if link not in links:
                            links.append(link)
                excerpt = next((line.strip()[:500] for line in body.splitlines()
                                if all(term in line.casefold() for term in terms)), "")
                results.append({"entry_type": "reference_file", "excerpt": excerpt, "title": entry["path"],
                                "result_kind": "reference_fulltext", "source": source["id"],
                                "revision": source["revision"], "revision_kind": "bundle_manifest_sha256",
                                "content_sha256": entry["sha256"], "path": entry["path"], "local_path": str(local),
                                "trust": "community_reference_bundle", "coverage": source["coverage"],
                                "uri": f"reference://{source['id']}@{source['revision']}/{entry['path']}",
                                "remote_url": source["origin_url"], "catalog_ids": [item["id"] for item in matching],
                                "links": links})
        return results

    def show(self, uri):
        match = re.fullmatch(r"reference://([^@/]+)@([0-9a-f]{64})/(.+)", uri)
        if not match:
            raise ReferenceError("Expected reference://SOURCE@MANIFEST_SHA256/PATH")
        source = self.source(match.group(1))
        if match.group(2) != source["revision"]:
            raise ReferenceError("Unknown reference bundle revision")
        path = match.group(3)
        snapshot = self.snapshot(source)
        safe_path(snapshot, path)
        remote = source["origin_url"]
        if not snapshot.exists():
            return {"content": None, "local_path": None, "remote_url": remote, "revision": source["revision"]}
        entry = self.manifest(source, snapshot).get(path)
        if entry is None:
            raise ReferenceError("File is not in the pinned reference manifest")
        local, content = self.verified_file(source, snapshot, entry)
        return {"content": content, "local_path": str(local), "remote_url": remote, "revision": source["revision"]}

    def follow(self, url):
        """Retrieve a cataloged public link as data; never execute or claim runtime validation."""
        links = [link for item in self.items for link in item["links"] if link["url"] == url]
        if not links:
            raise ReferenceError("Only links in the reviewed reference catalog can be followed")
        public_url(url)
        revision = links[0].get("revision")
        # An associated accepted snapshot does not pin a master/root web page's response.
        if not revision or revision not in urlparse(url).path.split("/"):
            revision = None
        report = {"url": url, "accessed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                  "revision": revision, "snapshot_uri": links[0].get("snapshot_uri"), "trust": "retrieved_unreviewed",
                  "warning": "HTTP success does not confirm a complete body. Read the actual content, pin mutable Git links, and compare applicability. No upstream code is executed."}
        try:
            request = Request(url, headers={"User-Agent": "N2S-reference-reader/1.0"})
            with build_opener(_HTTPSRedirect()).open(request, timeout=20) as response:
                content = response.read(2 * 1024 * 1024 + 1)
                if len(content) > 2 * 1024 * 1024:
                    raise ReferenceError("Linked content exceeds the 2 MiB reading limit")
                if not (response.headers.get_content_type().startswith("text/")
                        or response.headers.get_content_type() in {"application/json", "application/xml"}):
                    raise ReferenceError("Linked content is not a readable text document")
                body = content.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
                if response.headers.get_content_type() == "text/html":
                    parser = _PageText()
                    parser.feed(body)
                    body = "\n".join(line.strip() for line in "".join(parser.text).splitlines() if line.strip())
                report.update(status="retrieved", final_url=response.geturl(), content_sha256=checksum(content), text=body)
                if revision and revision not in urlparse(report["final_url"]).path.split("/"):
                    report["revision"] = None
        except (URLError, TimeoutError, OSError) as error:
            report.update(status="unavailable", error=str(error), text=None)
        return report
