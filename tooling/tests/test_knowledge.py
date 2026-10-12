import datetime as dt
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from n2s_knowledge.indexer import build_index, deterministic_json
from n2s_knowledge.manager import KnowledgeManager


N2S_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = N2S_ROOT / "upstreams" / "schemas"
CLI = N2S_ROOT / "tooling" / "n2s-knowledge"


def run(*args, cwd, input_text=None):
    return subprocess.run(
        list(args), cwd=cwd, input=input_text, text=True, check=True, capture_output=True
    ).stdout.strip()


class LocalUpstreamFixture:
    def __init__(self, base):
        self.base = Path(base)
        self.work = self.base / "official-work"
        self.remote = self.base / "official.git"
        self.root = self.base / "n2s"
        self.fixed_now = dt.datetime(2026, 9, 5, 12, 0, tzinfo=dt.timezone.utc)
        self.work.mkdir()
        run("git", "init", "-b", "master", cwd=self.work)
        run("git", "config", "user.email", "fixture@example.invalid", cwd=self.work)
        run("git", "config", "user.name", "Fixture", cwd=self.work)
        self.write("LICENSE", "fixture license v1\n")
        self.write("DISCLAIMER.md", "non-commercial fixture\n")
        self.write("Third_Party_Open_Source_Software_Notice", "third-party notice\n")
        self.write("README.md", "# Fixture official recipes\n")
        self.write("manipulation/pi0/README.md", "# PI0 fixture\nneedle fusion attention\n")
        self.write("third_party/vendor.py", "VALUE = 'vendor'\n")
        self.accepted = self.commit("initial accepted")
        run("git", "clone", "--mirror", str(self.work), str(self.remote), cwd=self.base)
        run("git", "remote", "add", "fixture", str(self.remote), cwd=self.work)

        (self.root / "upstreams").mkdir(parents=True)
        shutil.copytree(SCHEMAS, self.root / "upstreams" / "schemas")
        (self.root / "upstreams" / "knowledge").mkdir()
        (self.root / "upstreams" / "reviews").mkdir()
        (self.root / "upstreams" / "indexes").mkdir()
        (self.root / "rules").mkdir()
        (self.root / "rules" / "registry.json").write_text('{"sentinel": true}\n', encoding="utf-8")
        self.write_registry(self.remote)
        self.write_catalog()
        source = self.source(self.remote)
        accepted_index = build_index(self.remote, source, self.accepted)
        (self.root / "upstreams" / "indexes" / "fixture-official.json").write_text(
            deterministic_json(accepted_index), encoding="utf-8"
        )

    def write(self, relative, content):
        path = self.work / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def commit(self, message):
        run("git", "add", ".", cwd=self.work)
        run("git", "commit", "-m", message, cwd=self.work)
        return run("git", "rev-parse", "HEAD", cwd=self.work)

    def push(self, force=False):
        args = ["git", "push"]
        if force:
            args.append("--force")
        args.extend(["fixture", "master"])
        run(*args, cwd=self.work)

    def fingerprints(self, revision):
        result = {}
        for name in ("LICENSE", "DISCLAIMER.md", "Third_Party_Open_Source_Software_Notice"):
            content = subprocess.run(
                ["git", "show", f"{revision}:{name}"], cwd=self.work, check=True, capture_output=True
            ).stdout
            result[name] = hashlib.sha256(content).hexdigest()
        return result

    def source(self, remote):
        return {
            "acceptance_review": "upstreams/reviews/initial.json",
            "accepted_license_fingerprints": self.fingerprints(self.accepted),
            "accepted_revision": self.accepted,
            "authority": "official_upstream",
            "branch": "master",
            "browse_url_template": "https://example.invalid/official/blob/{revision}/{path}",
            "deep_index_scopes": ["manipulation/pi0"],
            "id": "fixture-official",
            "index_policy": "all_files_and_markdown_titles",
            "license_files": ["LICENSE", "DISCLAIMER.md", "Third_Party_Open_Source_Software_Notice"],
            "metadata_rules": [
                {
                    "devices": ["Fixture NPU"],
                    "model": "PI0",
                    "modes": ["online_inference"],
                    "prefix": "manipulation/pi0/",
                    "software_versions": {
                        "cann": ["fixture"], "framework": ["fixture"],
                        "pytorch": ["fixture"], "torch_npu": ["fixture"],
                    },
                }
            ],
            "remote_url": str(remote),
            "usage_restrictions": "fixture-only non-commercial reference",
        }

    def write_registry(self, remote):
        value = {"schema_version": "1.0.0", "sources": [self.source(remote)]}
        (self.root / "upstreams" / "sources.json").write_text(
            deterministic_json(value), encoding="utf-8"
        )

    def write_catalog(self):
        item = {
            "devices": ["Fixture NPU"],
            "id": "fixture.pi0",
            "models": ["PI0"],
            "modes": ["online_inference"],
            "n2s_validation": {"level": "not_verified", "status": "upstream_documented"},
            "official_claim": {
                "references": [{"path": "manipulation/pi0/README.md", "revision": self.accepted, "source": "fixture-official"}],
                "status": "official_statement",
                "summary": "Fixture PI0 uses fusion attention.",
            },
            "rule_relations": [],
            "scope": ["manipulation", "manipulation/pi0"],
            "software_versions": {"cann": ["fixture"], "framework": ["fixture"], "pytorch": ["fixture"], "torch_npu": ["fixture"]},
            "title": "Fixture PI0 knowledge",
            "type": "recipe",
        }
        (self.root / "upstreams" / "knowledge" / "fixture.json").write_text(
            deterministic_json({"items": [item], "schema_version": "1.0.0"}), encoding="utf-8"
        )

    def manager(self):
        return KnowledgeManager(self.root, now=lambda: self.fixed_now)


class KnowledgeSyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.fixture = LocalUpstreamFixture(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def make_community_snapshot(self):
        snapshot = self.fixture.root / "cases/validation-projects/community-fixture"
        snapshot.mkdir(parents=True)
        source = {
            "id": "community-fixture",
            "snapshot_path": "cases/validation-projects/community-fixture",
            "revision": self.fixture.accepted,
            "scopes": ["manipulation"],
            "browse_url_template": "https://example.invalid/community/blob/{revision}/{path}",
            "coverage": "Selected files; static detector validation only",
        }
        contents = {
            "LICENSE": "Fixture license\n",
            "REMOTE": "https://example.invalid/community.git\n",
            "REVISION": self.fixture.accepted + "\n",
            "src/adapter.py": "# cache alignment fixture\nVALUE = 'community-needle'\n",
        }
        for relative, body in contents.items():
            path = snapshot / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        (snapshot / "SHA256SUMS").write_text("".join(
            f"{hashlib.sha256(body.encode()).hexdigest()}  {relative}\n"
            for relative, body in sorted(contents.items())
        ), encoding="utf-8")
        (self.fixture.root / "upstreams/community-snapshots.json").write_text(
            json.dumps({"schema_version": "1.0.0", "sources": [source]}), encoding="utf-8"
        )
        return snapshot

    def test_selected_community_search_is_pinned_and_hash_checked(self):
        snapshot = self.make_community_snapshot()
        manager = self.fixture.manager()
        result = manager.search("community-needle", scope="manipulation", accepted_only=True,
                                include_community=True)
        self.assertEqual(1, len(result["results"]))
        item = result["results"][0]
        self.assertEqual("community_source_snapshot_static_only", item["trust"])
        self.assertEqual(self.fixture.accepted, item["revision"])
        self.assertEqual("Selected files; static detector validation only", item["coverage"])
        self.assertEqual("community-needle", manager.show_community(item["uri"])["content"].decode().split("'")[1])
        self.assertEqual([], manager.search("community-needle", scope="other", include_community=True)["results"])
        self.assertIsNone(manager.show_community(
            f"community://community-fixture@{self.fixture.accepted}/not-captured.py"
        )["content"])
        with self.assertRaisesRegex(Exception, "unsafe community snapshot path"):
            manager.show_community(f"community://community-fixture@{self.fixture.accepted}/../LICENSE")
        (snapshot / "src/adapter.py").write_text("tampered\n", encoding="utf-8")
        with self.assertRaisesRegex(Exception, "checksum mismatch"):
            manager.search("community-needle", include_community=True)

    def test_combined_search_keeps_git_and_bundle_revisions_and_trust_separate(self):
        self.make_community_snapshot()
        upstreams = self.fixture.root / "upstreams"
        catalog_path = upstreams / "catalogs/fixture.json"
        catalog_path.parent.mkdir()
        catalog_path.write_text(json.dumps({"schema_version": "1.0.0", "items": [{
            "id": "R01", "source": "fixture-reference", "title": "needle training reference",
            "summary": "needle training reference", "tasks": ["training"], "stages": ["optimization"],
            "scopes": ["general"], "keywords": ["needle"], "evidence": "reported_smoke",
            "conditions": "Mock inputs only", "limitations": "No official-weight accuracy",
            "references": [{"path": "README.md"}], "links": [{"url": "https://example.invalid/docs",
                "label": "Original", "authority": "community", "content_status": "partial", "revision": None}]
        }]}), encoding="utf-8")
        revision = "b" * 64
        (upstreams / "reference-bundles.json").write_text(json.dumps({"schema_version": "1.0.0", "bundles": [{
            "id": "fixture-reference", "revision": revision, "captured_at": "2026-10-05",
            "origin_url": "https://example.invalid/docs", "catalog": "upstreams/catalogs/fixture.json",
            "manifest_path": "manifest.json", "extra_files": [], "coverage": "Bundle fixture",
            "usage_restrictions": "Internal reference only", "missing_sources": []
        }]}), encoding="utf-8")
        manager = self.fixture.manager()
        manager.refresh()
        report = manager.search("needle", scope="manipulation", accepted_only=True, include_community=True,
                                task="training", stage="optimization")
        self.assertEqual({"official_fulltext", "community_source_snapshot", "reference_catalog"},
                         {item["result_kind"] for item in report["results"]})
        for item in report["results"]:
            for field in ("source", "revision", "path", "trust", "uri", "local_path", "remote_url"):
                self.assertIn(field, item)
            if item["source"] == "fixture-reference":
                self.assertEqual(revision, item["revision"])
                self.assertEqual("community_reference_bundle", item["trust"])
                self.assertIsNone(item["local_path"])
            else:
                self.assertEqual(self.fixture.accepted, item["revision"])
        self.assertEqual("not_imported", report["reference_bundles"][0]["status"])
        self.assertFalse(report["truncated"])

    def test_initial_clone_snapshot_hash_index_and_search_contract(self):
        manager = self.fixture.manager()
        rules_before = (self.fixture.root / "rules" / "registry.json").read_bytes()
        result = manager.refresh()
        self.assertEqual("current", result["action"])
        self.assertEqual(self.fixture.accepted, result["current_revision"])
        self.assertTrue((self.fixture.root / "upstreams/_cache/fixture-official/mirror.git").is_dir())
        current = self.fixture.root / "upstreams/_cache/fixture-official/current"
        self.assertTrue(current.is_symlink())
        self.assertEqual("fixture license v1\n", (current / "LICENSE").read_text())
        self.assertEqual("non-commercial fixture\n", (current / "DISCLAIMER.md").read_text())

        index_path = self.fixture.root / "upstreams/_cache/fixture-official/live-index.json"
        index = json.loads(index_path.read_text())
        by_path = {item["path"]: item for item in index["files"]}
        snapshot_file = current / "manipulation/pi0/README.md"
        self.assertEqual(hashlib.sha256(snapshot_file.read_bytes()).hexdigest(), by_path["manipulation/pi0/README.md"]["blob_sha256"])
        self.assertEqual(self.fixture.accepted, by_path["manipulation/pi0/README.md"]["revision"])
        self.assertEqual("blob_content", by_path["manipulation/pi0/README.md"]["sha256_basis"])
        self.assertEqual("PI0", by_path["manipulation/pi0/README.md"]["model"])
        self.assertEqual("third_party_or_separately_licensed", by_path["third_party/vendor.py"]["ownership"])
        self.assertEqual(rules_before, (self.fixture.root / "rules" / "registry.json").read_bytes())

        search = manager.search("needle", scope="manipulation")
        official = next(item for item in search["results"] if item["result_kind"] == "official_fulltext")
        for field in ("source", "revision", "path", "trust", "local_path", "remote_url", "uri"):
            self.assertTrue(official[field])
        curated = manager.search("fusion attention", scope="manipulation", accepted_only=True)
        self.assertTrue(any(item["result_kind"] == "curated_knowledge" for item in curated["results"]))
        curated_item = next(item for item in curated["results"] if item["result_kind"] == "curated_knowledge")
        self.assertEqual({"level": "not_verified", "status": "upstream_documented"},
                         curated_item["n2s_validation"])
        self.assertEqual([], curated_item["rule_relations"])

        shown = manager.show(f"upstream://fixture-official@{self.fixture.accepted}/manipulation/pi0/README.md")
        self.assertIn(b"needle", shown["content"])
        missing = manager.show(f"upstream://fixture-official@{self.fixture.accepted}/missing.md")
        self.assertIsNone(missing["content"])
        self.assertIn(self.fixture.accepted, missing["remote_url"])

    def test_deterministic_index_rebuild(self):
        manager = self.fixture.manager()
        manager.refresh()
        source = manager.sources["fixture-official"]
        first = deterministic_json(build_index(manager._mirror(source), source, self.fixture.accepted))
        second = deterministic_json(build_index(manager._mirror(source), source, self.fixture.accepted))
        self.assertEqual(first, second)

    def test_same_day_skips_network_and_force_fast_forwards(self):
        manager = self.fixture.manager()
        manager.refresh()
        self.fixture.write("manipulation/pi0/README.md", "# PI0 fixture\nnew remote text\n")
        latest = self.fixture.commit("normal update")
        self.fixture.push()
        moved = self.fixture.remote.with_name("official-temporarily-offline.git")
        self.fixture.remote.rename(moved)
        skipped = manager.refresh()
        self.assertEqual("skipped_already_attempted", skipped["action"])
        moved.rename(self.fixture.remote)
        updated = manager.refresh(force=True)
        self.assertEqual("unreviewed_update", updated["action"])
        self.assertEqual(latest, updated["current_revision"])
        self.assertEqual("new remote text\n", (self.fixture.root / "upstreams/_cache/fixture-official/current/manipulation/pi0/README.md").read_text().split("# PI0 fixture\n", 1)[1])

    def test_offline_force_keeps_last_snapshot_and_reports_stale(self):
        manager = self.fixture.manager()
        initial = manager.refresh()
        moved = self.fixture.remote.with_name("official-offline.git")
        self.fixture.remote.rename(moved)
        offline = manager.refresh(force=True)
        self.assertEqual("offline_fallback", offline["action"])
        self.assertTrue(offline["stale"])
        self.assertEqual(initial["current_revision"], offline["current_revision"])
        self.assertIn("offline", manager.status()["sources"][0]["update_status"])

    def test_license_change_fetches_but_blocks_switch(self):
        manager = self.fixture.manager()
        initial = manager.refresh()
        self.fixture.write("LICENSE", "fixture license v2\n")
        changed = self.fixture.commit("license change")
        self.fixture.push()
        result = manager.refresh(force=True)
        self.assertEqual("blocked_license_changed", result["action"])
        self.assertEqual(changed, result["remote_latest_revision"])
        self.assertEqual(initial["current_revision"], result["current_revision"])
        self.assertTrue(result["license_warning"])
        self.assertEqual("fixture license v1\n", (self.fixture.root / "upstreams/_cache/fixture-official/current/LICENSE").read_text())
        review = {
            "decision": "accept",
            "license_checked": True,
            "limitations": ["fixture license change only"],
            "remote_url": str(self.fixture.remote),
            "reviewed_at": "2026-09-05T14:00:00Z",
            "reviewer": "fixture license reviewer",
            "revision": changed,
            "source": "fixture-official",
            "summary": "Reviewed the fixture license change.",
        }
        review_path = self.fixture.base / "license-review.json"
        review_path.write_text(deterministic_json(review), encoding="utf-8")
        manager.accept("fixture-official", changed, review_path)
        self.assertEqual("fixture license v2\n", (self.fixture.root / "upstreams/_cache/fixture-official/current/LICENSE").read_text())

    def test_history_rewrite_fetches_but_blocks_switch(self):
        manager = self.fixture.manager()
        initial = manager.refresh()
        tree = run("git", "rev-parse", "HEAD^{tree}", cwd=self.fixture.work)
        orphan = run("git", "commit-tree", tree, cwd=self.fixture.work, input_text="rewritten root\n")
        run("git", "reset", "--hard", orphan, cwd=self.fixture.work)
        self.fixture.push(force=True)
        result = manager.refresh(force=True)
        self.assertEqual("blocked_history_rewrite", result["action"])
        self.assertEqual(orphan, result["remote_latest_revision"])
        self.assertEqual(initial["current_revision"], result["current_revision"])

    def test_remote_url_change_fetches_but_blocks_switch(self):
        manager = self.fixture.manager()
        initial = manager.refresh()
        second_remote = self.fixture.base / "replacement.git"
        run("git", "clone", "--mirror", str(self.fixture.work), str(second_remote), cwd=self.fixture.base)
        self.fixture.write_registry(second_remote)
        changed_manager = self.fixture.manager()
        result = changed_manager.refresh(force=True)
        self.assertEqual("blocked_remote_url_changed", result["action"])
        self.assertEqual(initial["current_revision"], result["current_revision"])

    def test_concurrent_force_sync_is_serialized(self):
        self.fixture.manager().refresh()
        commands = [
            subprocess.Popen(
                [str(CLI), "--root", str(self.fixture.root), "sync", "--force"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            for _ in range(2)
        ]
        results = [process.communicate(timeout=20) + (process.returncode,) for process in commands]
        self.assertEqual([0, 0], [result[2] for result in results], results)
        state = json.loads((self.fixture.root / "upstreams/_cache/state.json").read_text())
        self.assertEqual(self.fixture.accepted, state["sources"]["fixture-official"]["current_revision"])
        self.assertFalse(any(self.fixture.root.glob("upstreams/_cache/fixture-official/.current.tmp-*")))

    def test_diff_and_explicit_accept_do_not_change_rules(self):
        manager = self.fixture.manager()
        manager.refresh()
        rules_before = (self.fixture.root / "rules/registry.json").read_bytes()
        self.fixture.write("manipulation/pi0/README.md", "# PI0 fixture\nneedle changed\n")
        self.fixture.write("manipulation/pi0/config.yaml", "enabled: true\n")
        latest = self.fixture.commit("reviewable update")
        self.fixture.push()
        manager.refresh(force=True)
        difference = manager.diff()
        self.assertEqual(latest, difference["to"])
        self.assertIn("fixture.pi0", {item["id"] for item in difference["affected_knowledge"]})
        self.assertIn("configuration_or_version", {item["category"] for item in difference["high_attention"]})

        review = {
            "decision": "accept",
            "license_checked": True,
            "limitations": ["fixture only; no N2S rule promotion"],
            "remote_url": str(self.fixture.remote),
            "reviewed_at": "2026-09-05T13:00:00Z",
            "reviewer": "fixture reviewer",
            "revision": latest,
            "source": "fixture-official",
            "summary": "Reviewed fixture update.",
        }
        review_path = self.fixture.base / "review.json"
        review_path.write_text(deterministic_json(review), encoding="utf-8")
        accepted = manager.accept("fixture-official", latest, review_path)
        self.assertEqual(latest, accepted["accepted_revision"])
        registry = json.loads((self.fixture.root / "upstreams/sources.json").read_text())
        self.assertEqual(latest, registry["sources"][0]["accepted_revision"])
        index = json.loads((self.fixture.root / "upstreams/indexes/fixture-official.json").read_text())
        self.assertEqual(latest, index["revision"])
        state = manager.status()["sources"][0]
        self.assertEqual(latest, state["current_revision"])
        self.assertEqual("current", state["update_status"])
        self.assertEqual(rules_before, (self.fixture.root / "rules/registry.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
