import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from n2s_experiments.manager import ExperimentError, Experiments, ROOT, digest, file_hash, read_json


def command(*args, cwd):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "n2s"
        self.project = self.base / "mint"
        self.root.mkdir()
        self.project.mkdir()
        for directory in (self.root, self.project):
            command("git", "init", "-b", "main", cwd=directory)
            command("git", "config", "user.name", "Fixture", cwd=directory)
            command("git", "config", "user.email", "fixture@example.invalid", cwd=directory)
        shutil.copytree(ROOT / "evaluations/schemas", self.root / "evaluations/schemas")
        (self.root / "rules").mkdir()
        (self.root / "rules/registry.json").write_text('{"status":"candidate","auto_apply":false}\n')
        (self.root / "reviews/candidate-rules").mkdir(parents=True)
        (self.root / "reviews/candidate-rules/review.json").write_text('{"decision":"remain_candidate"}\n')
        (self.root / ".gitignore").write_text("evaluations/_local/\n__pycache__/\n")
        (self.project / "probe.py").write_text("print('fixed result: finite')\n")
        (self.project / ".gitignore").write_text("__pycache__/\noutputs/\n")
        for directory in (self.root, self.project):
            command("git", "add", ".", cwd=directory)
            command("git", "commit", "-m", "fixture baseline", cwd=directory)
        self.environment = {"devices": [{"backend": "cpu", "name": "fixture-cpu", "index": 0}],
                            "versions": {"python": "fixture"}, "errors": [], "interpreter": sys.executable}
        self.manager = Experiments(self.root, probe_fn=lambda python: self.environment.copy())
        self.before = self.manager.protected()
        self.manager.new_case("mint-trial", self.project, "Trial", "Finite output", "https://example.invalid/MINT.git", "cpu", ["MINT"])
        self.task_path = self.root / "cases/work-items/mint-trial/tasks/reproduce.json"
        self.key = "mint-trial/reproduce"

    def tearDown(self):
        self.temp.cleanup()

    def ready(self, argv=None, timeout=10):
        task = read_json(self.task_path)
        task["state"] = "ready"
        task["level"] = "integration"
        task["protocol"].update(input_description="Fixed scalar input 1", seed=7,
                                acceptance="The probe reports finite output", comparison_key="fixture-v1")
        task["execution"] = {"argv": argv or ["{python}", "probe.py"], "timeout_seconds": timeout,
                             "estimated_minutes": 1, "memory_gb": 0, "network": False, "installs_dependencies": False}
        write_json(self.task_path, task)
        return task

    def planned(self):
        return self.manager.plan(self.key, self.project)

    def run_plan(self):
        plan = self.planned()
        return self.manager.run(plan["plan"], plan["approval_token"])

    def test_intake_without_module_evidence_does_not_promote_rules(self):
        self.assertEqual("pending_validation", read_json(self.root / "cases/work-items/mint-trial/issue.json")["generalization"])
        self.assertEqual("draft", self.manager.task(self.key)["state"])
        self.assertEqual("valid", self.manager.validate()["status"])
        with self.assertRaisesRegex(ExperimentError, "Not runnable"):
            self.planned()
        self.assertEqual(self.before, self.manager.protected())

    def test_failure_logs_are_local_and_exit_zero_is_not_acceptance(self):
        self.ready(["{python}", "-c", "raise RuntimeError('fixture failure')"])
        result = self.run_plan()
        self.assertEqual("command_failed", result["status"])
        self.assertIn("RuntimeError: fixture failure", Path(result["raw_log"]).read_text())
        run = read_json(result["run"])
        self.assertEqual([], run["evidence"])
        with self.assertRaises(ExperimentError):
            self.manager.review(result["run"], "reviewer", "meets_task_acceptance", "bad approval")
        self.ready()
        success = self.run_plan()
        self.assertEqual("command_succeeded", success["status"])
        with self.assertRaisesRegex(ExperimentError, "Attach"):
            self.manager.review(success["run"], "reviewer", "meets_task_acceptance", "exit 0 is insufficient")
        self.assertEqual(self.before, self.manager.protected())

    def test_attach_review_dedup_and_task_change(self):
        self.ready()
        result = self.run_plan()
        original = Path(result["run"]).read_bytes()
        evidence = self.base / "sanitized.txt"
        evidence.write_text("Fixed scalar input 1; output is finite; actual helper call count 1.\n")
        report = self.manager.attach(result["run"], evidence, "Acceptance measurements", True)
        self.manager.review(report["run"], "fixture-reviewer", "meets_task_acceptance", "Checked fixed-output assertions")
        self.assertEqual(original, Path(result["run"]).read_bytes())
        self.assertEqual(1, len(self.manager.accepted_runs(self.key, self.manager.task(self.key))))
        duplicate = self.planned()
        with self.assertRaisesRegex(ExperimentError, "Matching reviewed evidence"):
            self.manager.run(duplicate["plan"], duplicate["approval_token"])
        repeat = self.manager.run(duplicate["plan"], duplicate["approval_token"], "Independent protocol audit")
        self.assertEqual("command_succeeded", repeat["status"])
        task = read_json(self.task_path)
        task["protocol"]["input_description"] = "Different input 2"
        write_json(self.task_path, task)
        self.assertEqual([], self.manager.accepted_runs(self.key, task))
        self.assertEqual("valid", self.manager.validate()["status"])
        self.assertEqual(self.before, self.manager.protected())

    def test_approval_required_single_use_and_source_drift(self):
        self.ready()
        plan = self.planned()
        with self.assertRaisesRegex(ExperimentError, "approval"):
            self.manager.run(plan["plan"], "wrong")
        (self.project / "new-helper.py").write_text("VALUE = 1\n")
        with self.assertRaisesRegex(ExperimentError, "Source"):
            self.manager.run(plan["plan"], plan["approval_token"])
        plan = self.planned()
        self.manager.run(plan["plan"], plan["approval_token"])
        with self.assertRaisesRegex(ExperimentError, "already consumed"):
            self.manager.run(plan["plan"], plan["approval_token"])

    def test_task_environment_and_asset_drift(self):
        self.ready()
        plan = self.planned()
        self.environment["versions"] = {"python": "different"}
        with self.assertRaisesRegex(ExperimentError, "Environment"):
            self.manager.run(plan["plan"], plan["approval_token"])
        plan = self.planned()
        task = read_json(self.task_path)
        task["claim"] = "changed claim"
        write_json(self.task_path, task)
        with self.assertRaisesRegex(ExperimentError, "Task changed"):
            self.manager.run(plan["plan"], plan["approval_token"])
        asset = self.base / "input.txt"
        asset.write_text("fixed input")
        task["protocol"]["assets"] = [{"name": str(asset), "sha256": file_hash(asset)}]
        write_json(self.task_path, task)
        plan = self.planned()
        asset.write_text("changed input")
        with self.assertRaisesRegex(ExperimentError, "Asset checksum"):
            self.manager.run(plan["plan"], plan["approval_token"])

    def test_runner_changes_require_new_approval(self):
        self.ready()
        plan = self.planned()
        runner = self.root / "tooling/n2s-experiments"
        runner.parent.mkdir()
        runner.write_text("# changed workflow\n")
        with self.assertRaisesRegex(ExperimentError, "runner or revision changed"):
            self.manager.run(plan["plan"], plan["approval_token"])

    def test_hardware_views_and_device_model_constraints(self):
        task = self.ready()
        task["requirements"]["backends"] = ["cuda", "npu"]
        task["requirements"]["device_name_contains"] = ["310P"]
        write_json(self.task_path, task)
        self.assertEqual(1, len(self.manager.queue("cuda")["tasks"]))
        self.assertEqual(1, len(self.manager.queue("npu")["tasks"]))
        self.assertEqual([], self.manager.queue("cpu")["tasks"])
        self.environment["devices"] = [{"backend": "npu", "name": "Ascend910B2C", "index": 0}]
        self.assertIn("hardware_mismatch", self.manager.queue()["tasks"][0]["blockers"])
        self.environment["devices"] = [{"backend": "npu", "name": "Ascend310P", "index": 0}]
        self.assertEqual([], self.manager.queue()["tasks"][0]["blockers"])
        task["requirements"]["versions"] = {"torch-npu": "2.5.1.post1"}
        write_json(self.task_path, task)
        self.assertIn("version_mismatch:torch-npu", self.manager.queue()["tasks"][0]["blockers"])

    def test_models_share_workflow_but_not_case_or_evidence_state(self):
        self.ready()
        self.run_plan()
        self.manager.new_case("pi05-trial", self.project, "Other model observation", "Independent validation",
                              "https://example.invalid/other-project.git", "npu", ["PI0.5"])
        original = self.manager.queue("cpu", model="mint")["tasks"]
        other = self.manager.queue("npu", model="pi0.5")["tasks"]
        self.assertEqual(1, len(original))
        self.assertEqual(1, original[0]["runs"])
        self.assertEqual(["PI0.5"], other[0]["models"])
        self.assertEqual("draft", other[0]["state"])
        self.assertEqual(0, other[0]["runs"])
        self.assertEqual(0, other[0]["accepted_runs"])
        self.assertEqual([], self.manager.queue("cuda", model="pi0.5")["tasks"])
        self.assertEqual("valid", self.manager.validate()["status"])
        self.assertEqual(self.before, self.manager.protected())

    def test_relabeling_case_cannot_reuse_model_evidence_or_approval(self):
        self.ready()
        result = self.run_plan()
        evidence = self.base / "measurements.txt"
        evidence.write_text("Fixed input and verified finite output")
        report = self.manager.attach(result["run"], evidence, "Measurements", True)
        self.manager.review(report["run"], "fixture-reviewer", "meets_task_acceptance", "Original model only")
        self.assertEqual(1, len(self.manager.accepted_runs(self.key, self.manager.task(self.key))))
        plan = self.planned()
        issue_path = self.root / "cases/work-items/mint-trial/issue.json"
        issue = read_json(issue_path)
        issue["models"] = ["PI0.5"]
        write_json(issue_path, issue)
        with self.assertRaisesRegex(ExperimentError, "model scope changed"):
            self.manager.run(plan["plan"], plan["approval_token"])
        rows = self.manager.queue("cpu", model="PI0.5")["tasks"]
        self.assertEqual(0, rows[0]["accepted_runs"])
        self.assertTrue(all(not run["matches_current_task"] for run in rows[0]["history"]))
        self.assertEqual("valid", self.manager.validate()["status"])

    def test_timeout_and_concurrency_lock(self):
        self.ready(["{python}", "-c", "import time; time.sleep(20)"], timeout=1)
        result = self.run_plan()
        self.assertEqual("timed_out", result["status"])
        plan = self.planned()
        with (self.root / "evaluations/_local/run.lock").open("a") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ExperimentError, "Another experiment"):
                self.manager.run(plan["plan"], plan["approval_token"])

    def test_manual_failure_and_secret_rejection(self):
        evidence = self.base / "report.txt"
        evidence.write_text("ModuleNotFoundError: package absent; no model execution\n")
        with self.assertRaisesRegex(ExperimentError, "confirm-sanitized"):
            self.manager.record(self.key, self.project, "blocked", "Missing dependency", evidence, False)
        record = self.manager.record(self.key, self.project, "blocked", "Missing dependency", evidence, True)
        self.manager.review(record["run"], "fixture-reviewer", "inconclusive", "Environment needs provisioning")
        evidence.write_text("access_token=" + "x" * 30)
        with self.assertRaisesRegex(ExperimentError, "credential"):
            self.manager.record(self.key, self.project, "reported_failure", "Failure", evidence, True)
        self.assertEqual(self.before, self.manager.protected())

    def test_paths_and_protected_writes_are_rejected(self):
        for case_id in ("../rules", "x/../../escape", "/tmp/escape"):
            with self.assertRaises(ExperimentError):
                self.manager.new_case(case_id, self.project, "bad", "bad", "fixture")
        with self.assertRaises(ExperimentError):
            self.manager.write("rules/registry.json", {})
        with self.assertRaises(ExperimentError):
            self.manager.source(self.root)
        (self.root / "cases/work-items/escape-case").symlink_to(self.project)
        with self.assertRaisesRegex(ExperimentError, "escapes|Symlinks"):
            self.manager.path("cases/work-items/escape-case/issue.json")
        self.assertEqual(self.before, self.manager.protected())

    def test_rule_write_by_untrusted_command_is_detected_not_reverted(self):
        sentinel = self.root / "rules/registry.json"
        script = f"from pathlib import Path; Path({str(sentinel)!r}).write_text('changed by fixture')"
        self.ready(["{python}", "-c", script])
        result = self.run_plan()
        self.assertEqual("safety_violation", result["status"])
        self.assertEqual("changed by fixture", sentinel.read_text())

    def test_dependency_cycle_and_missing_dependency(self):
        task = self.ready()
        task["depends_on"] = [self.key]
        write_json(self.task_path, task)
        with self.assertRaisesRegex(ExperimentError, "cycle"):
            self.manager.validate()
        task["depends_on"] = ["missing-case/missing-task"]
        write_json(self.task_path, task)
        with self.assertRaises(FileNotFoundError):
            self.manager.validate()

    def test_evidence_checksum_and_review_integrity(self):
        evidence = self.base / "report.txt"
        evidence.write_text("Failure at initialization\n")
        record = self.manager.record(self.key, self.project, "reported_failure", "Observed failure", evidence, True)
        self.manager.review(record["run"], "reviewer", "does_not_meet", "No inference")
        path = Path(record["run"])
        path.with_name("evidence.txt").write_text("tampered")
        with self.assertRaisesRegex(ExperimentError, "checksum"):
            self.manager.validate()
        path.with_name("evidence.txt").write_text("Failure at initialization\n")
        run = read_json(path)
        run["summary"] = "tampered summary"
        write_json(path, run)
        with self.assertRaisesRegex(ExperimentError, "changed run"):
            self.manager.validate()

    def test_publish_is_case_only_no_network_and_records_are_immutable(self):
        command("git", "add", "cases/work-items/mint-trial", cwd=self.root)
        result = self.manager.publish_check("mint-trial")
        self.assertEqual("ready_for_user_review", result["status"])
        (self.root / "unrelated.txt").write_text("user content")
        command("git", "add", "unrelated.txt", cwd=self.root)
        with self.assertRaisesRegex(ExperimentError, "Stage only"):
            self.manager.publish_check("mint-trial")
        command("git", "commit", "-m", "fixture state", cwd=self.root)
        evidence = self.base / "report.txt"
        evidence.write_text("Original failure report")
        result = self.manager.record(self.key, self.project, "reported_failure", "failure", evidence, True)
        command("git", "add", "cases/work-items/mint-trial", cwd=self.root)
        self.manager.publish_check("mint-trial")
        command("git", "commit", "-m", "record failure", cwd=self.root)
        run = read_json(result["run"])
        run["summary"] = "rewritten history"
        write_json(Path(result["run"]), run)
        command("git", "add", "cases/work-items/mint-trial", cwd=self.root)
        with self.assertRaisesRegex(ExperimentError, "immutable"):
            self.manager.publish_check("mint-trial")

    def test_cross_host_records_are_visible_without_transferring_approval(self):
        self.ready()
        result = self.run_plan()
        command("git", "add", "cases/work-items/mint-trial", cwd=self.root)
        command("git", "commit", "-m", "first host evidence", cwd=self.root)
        remote = self.base / "central.git"
        command("git", "clone", "--bare", str(self.root), str(remote), cwd=self.base)
        other = self.base / "other-n2s"
        command("git", "clone", str(remote), str(other), cwd=self.base)
        manager = Experiments(other, probe_fn=lambda python: self.environment)
        self.assertEqual(1, manager.queue("cpu")["tasks"][0]["runs"])
        self.assertFalse((other / "evaluations/_local").exists())
        self.assertEqual("valid", manager.validate()["status"])
        with self.assertRaisesRegex(ExperimentError, "locally generated"):
            manager.run(result["run"], "anything")
        second_plan = manager.plan(self.key, self.project)
        second = manager.run(second_plan["plan"], second_plan["approval_token"])
        self.assertEqual("command_succeeded", second["status"])
        self.assertEqual(2, manager.queue("cpu")["tasks"][0]["runs"])
        self.assertEqual(self.before, manager.protected())
        command("git", "config", "user.name", "Second fixture host", cwd=other)
        command("git", "config", "user.email", "second@example.invalid", cwd=other)
        command("git", "add", "cases/work-items/mint-trial", cwd=other)
        manager.publish_check("mint-trial")
        command("git", "commit", "-m", "second host result", cwd=other)
        command("git", "push", "origin", "HEAD:main", cwd=other)
        command("git", "fetch", str(remote), "main", cwd=self.root)
        changed = command("git", "diff", "--name-only", "main...FETCH_HEAD", cwd=self.root).splitlines()
        self.assertTrue(changed)
        self.assertTrue(all(name.startswith("cases/work-items/mint-trial/") for name in changed))

    def test_publish_rejects_code_even_inside_case_directory(self):
        path = self.root / "cases/work-items/mint-trial/copied_upstream.py"
        path.write_text("print('not a case record')\n")
        command("git", "add", "cases/work-items/mint-trial", cwd=self.root)
        with self.assertRaisesRegex(ExperimentError, "Only case metadata"):
            self.manager.publish_check("mint-trial")

    def test_attached_report_cannot_rewrite_original_provenance(self):
        self.ready()
        result = self.run_plan()
        evidence = self.base / "measurements.txt"
        evidence.write_text("Finite output for fixed input 1")
        report = self.manager.attach(result["run"], evidence, "Reviewed measurements", True)
        path = Path(report["run"])
        value = read_json(path)
        value["source"]["revision"] = "0" * 40
        write_json(path, value)
        with self.assertRaisesRegex(ExperimentError, "provenance"):
            self.manager.validate()


if __name__ == "__main__":
    unittest.main()
