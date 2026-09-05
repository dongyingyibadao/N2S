import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath
from urllib.parse import quote


TEXT_EXTENSIONS = {
    "", ".c", ".cc", ".cfg", ".cmake", ".conf", ".cpp", ".css", ".csv",
    ".h", ".hpp", ".html", ".ini", ".java", ".js", ".json", ".md",
    ".patch", ".py", ".rst", ".sh", ".toml", ".ts", ".txt", ".xml",
    ".yaml", ".yml",
}


class IndexError(RuntimeError):
    pass


def _git(git_dir, *args, text=False):
    command = [
        "git", "-c", "core.hooksPath=/dev/null", f"--git-dir={git_dir}", *args
    ]
    try:
        return subprocess.run(command, check=True, capture_output=True, text=text).stdout
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() if isinstance(error.stderr, str) else error.stderr.decode("utf-8", "replace").strip()
        raise IndexError(detail or f"git command failed: {' '.join(args)}") from error


def list_tree(git_dir, revision):
    raw = _git(git_dir, "ls-tree", "-rz", "--full-tree", revision)
    entries = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, object_type, object_id = metadata.decode("ascii").split()
        path = raw_path.decode("utf-8", "surrogateescape")
        pure = PurePosixPath(path)
        if pure.is_absolute() or ".." in pure.parts:
            raise IndexError(f"unsafe upstream path: {path!r}")
        entries.append({"mode": mode, "git_object_type": object_type, "git_object_id": object_id, "path": path})
    return entries


def read_object(git_dir, object_id):
    return _git(git_dir, "cat-file", "blob", object_id)


def _title(content):
    try:
        source = content.decode("utf-8")
    except UnicodeDecodeError:
        return None
    for line in source.splitlines():
        match = re.match(r"^\s*#{1,3}\s+(.+?)\s*$", line)
        if match:
            return match.group(1).strip("# ")[:300]
    return None


def _file_type(path, object_type):
    if object_type == "commit":
        return "submodule"
    name = PurePosixPath(path).name.lower()
    suffix = PurePosixPath(path).suffix.lower()
    if name.startswith(("license", "copying")) or "notice" in name or name == "disclaimer.md":
        return "license"
    if suffix in {".md", ".rst", ".txt"} or name.startswith("readme"):
        return "document"
    if suffix == ".patch":
        return "patch"
    if suffix in {".json", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".conf"}:
        return "configuration"
    if suffix in {".py", ".sh", ".c", ".cc", ".cpp", ".h", ".hpp", ".js", ".ts", ".java"}:
        return "code"
    if suffix in TEXT_EXTENSIONS:
        return "text"
    return "binary"


def _metadata(source, path):
    matches = [rule for rule in source.get("metadata_rules", []) if path.startswith(rule["prefix"])]
    rule = max(matches, key=lambda value: len(value["prefix"])) if matches else {}
    return {
        "model": rule.get("model"),
        "modes": rule.get("modes", []),
        "devices": rule.get("devices", []),
        "software_versions": rule.get(
            "software_versions",
            {"cann": [], "pytorch": [], "torch_npu": [], "framework": []},
        ),
    }


def _ownership(path):
    parts = {part.casefold() for part in PurePosixPath(path).parts}
    name = PurePosixPath(path).name.casefold()
    if (
        parts.intersection({"third_party", "third-party", "extern", "vendor", "licenses"})
        or "third_party" in name
        or "third-party" in name
        or name.startswith(("license", "copying"))
        or "notice" in name
    ):
        return "third_party_or_separately_licensed"
    return "upstream_repository"


def build_index(git_dir, source, revision):
    revision = _git(git_dir, "rev-parse", f"{revision}^{{commit}}", text=True).strip()
    files = []
    for entry in list_tree(git_dir, revision):
        content = None
        if entry["git_object_type"] == "blob":
            content = read_object(git_dir, entry["git_object_id"])
            digest_input = content
            blob_sha256 = hashlib.sha256(content).hexdigest()
            sha256_basis = "blob_content"
        else:
            digest_input = entry["git_object_id"].encode("ascii")
            blob_sha256 = None
            sha256_basis = "gitlink_commit_id"
        metadata = _metadata(source, entry["path"])
        file_type = _file_type(entry["path"], entry["git_object_type"])
        files.append(
            {
                "blob_sha256": blob_sha256,
                "devices": metadata["devices"],
                "entry_sha256": hashlib.sha256(digest_input).hexdigest(),
                "git_object_id": entry["git_object_id"],
                "git_object_type": entry["git_object_type"],
                "mode": entry["mode"],
                "model": metadata["model"],
                "modes": metadata["modes"],
                "ownership": _ownership(entry["path"]),
                "path": entry["path"],
                "revision": revision,
                "sha256_basis": sha256_basis,
                "source": source["id"],
                "software_versions": metadata["software_versions"],
                "title": _title(content) if content is not None and file_type == "document" else None,
                "type": file_type,
                "url": source["browse_url_template"].format(
                    revision=revision, path=quote(entry["path"], safe="/")
                ),
            }
        )
    return {
        "files": files,
        "revision": revision,
        "schema_version": "1.0.0",
        "source": source["id"],
        "trust": "upstream_documented",
    }


def deterministic_json(value):
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
