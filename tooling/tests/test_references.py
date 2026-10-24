import hashlib
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from n2s_knowledge.cli import _print_search
from n2s_knowledge.references import ReferenceError, ReferenceLibrary


ROOT = Path(__file__).resolve().parents[2]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "n2s"
        self.bundle = self.base / "bundle"
        self.bundle.mkdir()
        shutil.copytree(ROOT / "upstreams/schemas", self.root / "upstreams/schemas")
        (self.root / "rules").mkdir()
        (self.root / "rules/registry.json").write_text("protected\n")
        self.files = {"README.md": "# Reference\n", "报告.md": "# Training\nneedle fusion RMSNorm\n",
                      "unsafe.sh": "touch SHOULD_NEVER_EXIST\n", "LICENSE": "fixture third-party notice\n"}
        entries = []
        for path, text in self.files.items():
            content = text.encode()
            (self.bundle / path).write_bytes(content)
            entries.append({"path": path, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()})
        write_json(self.bundle / "manifest.json", {"files": entries})
        self.revision = hashlib.sha256((self.bundle / "manifest.json").read_bytes()).hexdigest()
        self.source = {"id": "fixture-reference", "revision": self.revision, "captured_at": "2026-10-05",
                       "origin_url": "https://example.invalid/source", "catalog": "upstreams/catalogs/fixture.json",
                       "manifest_path": "manifest.json", "extra_files": [], "coverage": "Static reference data only",
                       "usage_restrictions": "Internal reference with third-party notices", "missing_sources": ["unavailable report"]}
        write_json(self.root / "upstreams/reference-bundles.json", {"schema_version": "1.0.0", "bundles": [self.source]})
        self.item = {"id": "R01", "source": "fixture-reference", "title": "Training reference", "summary": "needle fusion RMSNorm",
                     "tasks": ["training", "performance"], "stages": ["preparation", "optimization"], "scopes": ["general"],
                     "keywords": ["fusion", "RMSNorm"], "evidence": "reported_smoke", "conditions": "Mock input only",
                     "limitations": "No official-weight accuracy evidence", "references": [{"path": "报告.md"}],
                     "links": [{"url": "https://example.invalid/docs", "label": "Original", "authority": "community",
                                "revision": None, "content_status": "partial"}]}
        write_json(self.root / "upstreams/catalogs/fixture.json", {"schema_version": "1.0.0", "items": [self.item]})
        self.library = ReferenceLibrary(self.root)

    def tearDown(self):
        for path in self.base.rglob("*"):
            if path.is_dir() and not path.is_symlink():
                path.chmod(0o755)
        self.temp.cleanup()

    def test_catalog_is_portable_without_private_bundle_and_routes_by_task(self):
        report = self.library.guide("training", "preparation")
        self.assertEqual("not_imported", report["reference_bundles"][0]["status"])
        result = report["results"][0]
        self.assertIsNone(result["local_path"])
        self.assertEqual(self.revision, result["revision"])
        self.assertEqual("community_reference_bundle", result["trust"])
        self.assertEqual("not_verified", result["n2s_validation"]["status"])
        self.assertEqual(result["uri"], result["references"][0]["uri"])
        self.assertEqual([], self.library.guide("simulation")["results"])
        self.assertEqual([], self.library.guide("training", "troubleshooting")["results"])
        self.assertIsNone(self.library.show(result["uri"])["content"])

    def test_import_preserves_hashes_notices_and_inert_scripts(self):
        report = self.library.import_bundle("fixture-reference", self.bundle)
        self.assertEqual(5, report["files"])
        snapshot = Path(report["snapshot"])
        for path, text in self.files.items():
            self.assertEqual(text.encode(), (snapshot / path).read_bytes())
            self.assertEqual(0, (snapshot / path).stat().st_mode & 0o333)
        self.assertFalse((snapshot / "SHOULD_NEVER_EXIST").exists())
        self.assertEqual("already_imported", self.library.import_bundle("fixture-reference", self.bundle)["action"])
        results = self.library.search(["needle"], task="training", stage="optimization", scope="manipulation")
        self.assertEqual({"reference_catalog", "reference_fulltext"}, {item["result_kind"] for item in results})
        fulltext = next(item for item in results if item["result_kind"] == "reference_fulltext")
        self.assertEqual(self.files["报告.md"].encode(), self.library.show(fulltext["uri"])["content"])
        self.assertTrue(fulltext["content_sha256"])
        self.assertEqual(["R01"], fulltext["catalog_ids"])
        self.assertEqual("protected\n", (self.root / "rules/registry.json").read_text())

    def test_manifest_and_content_tampering_are_rejected_without_partial_snapshot(self):
        (self.bundle / "报告.md").write_text("tampered")
        with self.assertRaisesRegex(ReferenceError, "checksum mismatch"):
            self.library.import_bundle("fixture-reference", self.bundle)
        self.assertFalse(self.library.snapshot(self.source).exists())
        (self.bundle / "报告.md").write_text(self.files["报告.md"])
        self.library.import_bundle("fixture-reference", self.bundle)
        local = self.library.snapshot(self.source) / "报告.md"
        local.chmod(0o644)
        local.write_text("tampered snapshot")
        self.assertEqual("invalid", self.library.status()[0]["status"])
        with self.assertRaisesRegex(ReferenceError, "checksum mismatch"):
            self.library.search(["needle"])
        with self.assertRaisesRegex(ReferenceError, "checksum mismatch"):
            self.library.show(f"reference://fixture-reference@{self.revision}/报告.md")

    def test_unknown_revision_path_escape_and_symlinks_are_rejected(self):
        for path in ("../rules/registry.json", "/etc/passwd", "x/../../outside"):
            with self.assertRaises(ReferenceError):
                self.library.show(f"reference://fixture-reference@{self.revision}/{path}")
        with self.assertRaisesRegex(ReferenceError, "revision"):
            self.library.show("reference://fixture-reference@" + "0" * 64 + "/报告.md")
        (self.bundle / "报告.md").unlink()
        (self.bundle / "报告.md").symlink_to(self.bundle / "README.md")
        with self.assertRaisesRegex(ReferenceError, "symlinks"):
            self.library.import_bundle("fixture-reference", self.bundle)

    def test_follow_is_cataloged_text_only_and_never_labels_http_success_as_validation(self):
        content = b"<h1>Original</h1><script>touch bad</script><p>needle fusion</p>"
        response = io.BytesIO(content)
        response.headers = Message()
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        response.geturl = lambda: "https://example.invalid/docs"
        with patch("n2s_knowledge.references.build_opener") as opener:
            opener.return_value.open.return_value = response
            report = self.library.follow("https://example.invalid/docs")
        self.assertEqual("retrieved_unreviewed", report["trust"])
        self.assertEqual(hashlib.sha256(content).hexdigest(), report["content_sha256"])
        self.assertIn("needle fusion", report["text"])
        self.assertNotIn("touch bad", report["text"])
        self.assertIsNone(report["revision"])
        with self.assertRaisesRegex(ReferenceError, "reviewed reference catalog"):
            self.library.follow("https://not-cataloged.invalid/unknown")

    def test_mutable_links_and_redirects_do_not_inherit_associated_git_revision(self):
        fixed_revision = "a" * 40
        self.library.items[0]["links"][0].update(revision=fixed_revision, snapshot_uri=f"upstream://fixture@{fixed_revision}/README.md")
        fixed_url = f"https://example.invalid/{fixed_revision}/README.md"
        self.library.items[0]["links"].append({**self.library.items[0]["links"][0], "url": fixed_url})

        def retrieve(url, final_url):
            response = io.BytesIO(b"Readable fixture")
            response.headers = Message()
            response.headers["Content-Type"] = "text/plain; charset=utf-8"
            response.geturl = lambda: final_url
            with patch("n2s_knowledge.references.build_opener") as opener:
                opener.return_value.open.return_value = response
                return self.library.follow(url)

        report = retrieve("https://example.invalid/docs", "https://example.invalid/docs")
        self.assertIsNone(report["revision"])
        self.assertIn(fixed_revision, report["snapshot_uri"])
        self.assertEqual(fixed_revision, retrieve(fixed_url, fixed_url)["revision"])
        self.assertIsNone(retrieve(fixed_url, "https://example.invalid/main/README.md")["revision"])

    def test_shared_fulltext_file_routes_to_the_matching_catalog_links(self):
        second = {**self.item, "id": "R02", "summary": "needle compiler", "keywords": ["compiler"],
                  "links": [{**self.item["links"][0], "url": "https://example.invalid/compiler"}]}
        self.library.items.append(second)
        self.library.import_bundle("fixture-reference", self.bundle)
        report = self.library.search(["needle"])
        file = next(entry for entry in report if entry["result_kind"] == "reference_fulltext")
        self.assertEqual(["R01", "R02"], file["catalog_ids"])
        self.assertEqual({"https://example.invalid/docs", "https://example.invalid/compiler"}, {link["url"] for link in file["links"]})

    def mocked_follow(self, url, pages, from_url=None):
        requested = []

        def open_page(request, timeout):
            requested.append(request.full_url)
            body, content_type, final_url = pages[request.full_url]
            if isinstance(body, Exception):
                raise body
            response = io.BytesIO(body.encode())
            response.headers = Message()
            response.headers["Content-Type"] = content_type
            response.geturl = lambda: final_url or request.full_url
            return response

        with patch("n2s_knowledge.references.build_opener") as opener:
            opener.return_value.open.side_effect = open_page
            result = self.library.follow(url, from_url=from_url)
        return result, requested

    def test_follow_relative_fixed_commit_links_and_multiple_parents_require_actual_provenance(self):
        revision = "b" * 40
        root = f"https://raw.githubusercontent.com/Fixture/Project/{revision}/ASCEND_SUPPORTS.md"
        parent = f"https://raw.githubusercontent.com/Fixture/Project/{revision}/src/README.md"
        child = f"https://raw.githubusercontent.com/Fixture/Project/{revision}/src/adapter.py"
        root_body = "# Source guide\nRead [`src/README.md`](src/README.md) for implementation.\n"
        parent_body = "# Adapter\nSee [actual adapter](adapter.py#L1).\n"
        child_body = "# inert source fixture\nraise RuntimeError('must never execute')\n"
        self.library.items[0]["links"].append({"url": root, "revision": revision})
        pages = {root: (root_body, "text/plain; charset=utf-8", None),
                 parent: (parent_body, "text/plain; charset=utf-8", None),
                 child: (child_body, "text/plain; charset=utf-8", None)}
        report, requested = self.mocked_follow(child, pages, from_url=[root, parent])
        self.assertEqual([root, parent, child], requested)
        self.assertEqual(revision, report["revision"])
        self.assertEqual(child_body, report["text"])
        self.assertEqual([parent, child], [entry["next_url"] for entry in report["lineage"]])
        self.assertEqual(hashlib.sha256(root_body.encode()).hexdigest(), report["lineage"][0]["content_sha256"])
        self.assertEqual("retrieved_unreviewed", report["trust"])
        with self.assertRaisesRegex(ReferenceError, "freshly read parent"):
            self.mocked_follow(child, pages, from_url=root)
        with self.assertRaisesRegex(ReferenceError, "reviewed reference catalog"):
            self.mocked_follow(child, pages, from_url=parent)

    def test_partial_navigation_can_reveal_a_child_without_claiming_the_parent_solution_was_read(self):
        root, child = "https://example.invalid/docs", "https://example.invalid/actual.py"
        pages = {root: ('<nav><a href="actual.py">Source</a><a href="/help">Help</a><a href="/login">Login</a></nav>', "text/html", None),
                 child: ("# actual implementation fixture", "text/plain", None)}
        root_report, _ = self.mocked_follow(root, pages)
        self.assertEqual("partial", root_report["status"])
        self.assertEqual("navigation_only", root_report["body_status"])
        self.assertIn(child, [link["url"] for link in root_report["discovered_links"]])
        child_report, requested = self.mocked_follow(child, pages, from_url=root)
        self.assertEqual([root, child], requested)
        self.assertEqual("retrieved", child_report["status"])
        self.assertEqual("navigation_only", child_report["lineage"][0]["body_status"])

    def test_login_javascript_empty_and_parent_failure_are_explicit_not_successful_reads(self):
        root = "https://example.invalid/docs"
        for body, expected in (("<form><input type='password'>Sign in</form>", "login_required"),
                               ("<main>Please enable JavaScript to read this repository</main>", "partial"),
                               ("<script>renderRequestedSource()</script>", "empty")):
            report, _ = self.mocked_follow(root, {root: (body, "text/html", None)})
            self.assertEqual("partial", report["status"])
            self.assertEqual(expected, report["body_status"])
        report, requested = self.mocked_follow("https://example.invalid/child.py",
                                              {root: (URLError("offline fixture"), "text/plain", None)}, from_url=root)
        self.assertEqual([root], requested)
        self.assertEqual("unavailable", report["status"])
        self.assertIn("child was not requested", report["error"])
        with self.assertRaisesRegex(ReferenceError, "HTTPS"):
            self.library.follow("http://example.invalid/child.py", from_url=root)

    def test_reference_context_preserves_textual_conditions_and_keeps_structured_unknowns(self):
        profile = {"task": "training", "model": "AnyModel", "device": "Any NPU", "software_versions": {"cann": "9.0"}}
        report = self.library.guide("training", "preparation", profile=profile)
        result = report["results"][0]
        fields = {field["field"]: field for field in result["context_comparison"]["fields"]}
        self.assertEqual("matched", fields["task"]["status"])
        self.assertEqual("unknown", fields["model"]["status"])
        self.assertEqual("unknown", fields["software_versions.cann"]["status"])
        self.assertEqual("Mock input only", result["conditions"])
        self.assertEqual("No official-weight accuracy evidence", result["limitations"])
        self.assertEqual(self.revision, result["references"][0]["revision"])
        self.assertEqual("bundle_manifest_sha256", result["references"][0]["revision_kind"])

    def test_text_renderer_accepts_legacy_reference_metadata_without_mislabeling_origin_as_exact_file(self):
        report = self.library.guide("training")
        reference = report["results"][0]["references"][0]
        self.assertIsNone(reference["remote_url"])
        reference.pop("trust")
        reference.pop("remote_url")
        output = io.StringIO()
        with redirect_stdout(output):
            _print_search(report)
        text = output.getvalue()
        self.assertIn(f"reference://fixture-reference@{self.revision}/报告.md [community_reference_bundle]", text)
        self.assertIn("remote: not provided for this exact file", text)
        self.assertIn("bundle origin (not an exact file URL): https://example.invalid/source", text)


if __name__ == "__main__":
    unittest.main()
