import fcntl
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import jsonschema

from n2s_experiments.cli import main as experiments_main
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

    def test_bootstrap_changes_require_new_execution_approval(self):
        bootstrap = self.root / "tooling/bootstrap.py"
        bootstrap.parent.mkdir()
        bootstrap.write_text("# original launcher\n")
        self.ready()
        plan = self.planned()
        bootstrap.write_text("# changed launcher\n")
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

    def feedback_event(self, kind, stage="troubleshooting", case_id="mint-trial", **fields):
        path = self.base / "feedback.json"
        write_json(path, {"kind": kind, "stage": stage, "summary": "Fixture observation", **fields})
        return self.manager.feedback(case_id, path, True)

    def lookup_event(self, stage, resolves=None, case_id="mint-trial"):
        return self.feedback_event("lookup", stage, case_id=case_id, queries=["fusion RMSNorm"], resolves=resolves or [], source_checks=[{
            "uri": "upstream://fixture@" + "a" * 40 + "/README.md", "url": "https://example.invalid/README.md",
            "accessed_at": "2026-10-12", "status": "read", "trust": "accepted_upstream_documented",
            "claim": "Fixture fused path", "applicability": "related", "comparison": "Actual target requires a measured A/B"}])

    def validation_event(self, stage="optimization", case_id="mint-trial", **changes):
        evidence = self.root / f"cases/work-items/{case_id}/measurements.md"
        evidence.write_text("Fixture official weights, fixed input, finite output, scoped error and same-device A/B")
        validation = {"functional": "passed", "official_weights": True, "actual_backend": "npu", "finite_outputs": True,
                      "accuracy": "passed", "accuracy_protocol": "Same official weights and input; agreed error <= 0.01",
                      "optimization": "measured_improvement", "performance": {"metric": "step_seconds", "direction": "lower",
                      "baseline": 2.0, "modified": 1.0, "same_device": True, "protocol": "Fixed batch, dtype, 5 warmup + 20 timed steps"}}
        validation.update(changes)
        return self.feedback_event("validation", stage, case_id=case_id, environment="fixture backend only", validation=validation,
                                   evidence_refs=[f"cases/work-items/{case_id}/measurements.md"])

    def functional_event(self, case_id="mint-trial"):
        return self.validation_event(stage="troubleshooting", case_id=case_id, optimization="pending",
                                     performance={"metric": "step_seconds", "direction": "lower", "baseline": None,
                                                  "modified": None, "same_device": False, "protocol": "pending: optimization A/B"})

    def test_feedback_records_each_error_and_three_stage_closure_without_device_use(self):
        self.manager.probe = lambda python: self.fail("Feedback must not discover or use hardware")
        self.lookup_event("preparation")
        failure = self.feedback_event("numerical_issue", environment="fixture NPU BF16", error={
            "type": "AccuracyMismatch", "message": "Error exceeds scoped tolerance", "expected": "<=0.01", "observed": "0.2"})
        self.assertIn(failure["id"], self.manager.workflow_check("mint-trial")["unresolved_events"])
        self.lookup_event("troubleshooting", [failure["id"]])
        self.functional_event()
        self.lookup_event("optimization")
        self.validation_event()
        self.feedback_event("resolution", resolves=[failure["id"]],
                            evidence_refs=["cases/work-items/mint-trial/measurements.md"])
        report = self.manager.workflow_check("mint-trial")
        self.assertTrue(report["completion_ready"])
        self.assertEqual("pending_validation", report["generalization"])
        issue_path = self.root / "cases/work-items/mint-trial/issue.json"
        issue = read_json(issue_path)
        issue["state"] = "resolved"
        write_json(issue_path, issue)
        self.assertEqual("valid", self.manager.validate()["status"])
        self.assertEqual(self.before, self.manager.protected())

    def test_missing_accuracy_cross_device_timing_and_false_gain_do_not_complete_case(self):
        self.lookup_event("preparation")
        self.functional_event()
        self.lookup_event("optimization")
        self.validation_event(accuracy="pending")
        self.assertIn("agreed_accuracy_comparison_not_verified", self.manager.workflow_check("mint-trial")["gaps"])
        performance = {"metric": "step_seconds", "direction": "lower", "baseline": 1.0, "modified": 2.0,
                       "same_device": False, "protocol": "GPU vs NPU"}
        self.validation_event(performance=performance)
        self.assertIn("same_device_optimization_gain_not_verified", self.manager.workflow_check("mint-trial")["gaps"])
        issue_path = self.root / "cases/work-items/mint-trial/issue.json"
        issue = read_json(issue_path)
        issue["state"] = "resolved"
        write_json(issue_path, issue)
        with self.assertRaisesRegex(ExperimentError, "incomplete migration workflow"):
            self.manager.validate()

    def test_open_incomplete_cases_publish_and_feedback_history_is_immutable(self):
        self.lookup_event("preparation")
        record = self.feedback_event("failure", environment="fixture missing dependency", error={
            "type": "ModuleNotFoundError", "message": "Missing package", "expected": "Load model", "observed": "Import failure"})
        command("git", "add", "cases/work-items/mint-trial", cwd=self.root)
        self.manager.publish_check("mint-trial")
        self.assertFalse(self.manager.workflow_check("mint-trial")["completion_ready"])
        command("git", "commit", "-m", "fixture feedback", cwd=self.root)
        event = read_json(record["event"])
        event["summary"] = "rewritten"
        write_json(Path(record["event"]), event)
        command("git", "add", "cases/work-items/mint-trial", cwd=self.root)
        with self.assertRaisesRegex(ExperimentError, "immutable"):
            self.manager.publish_check("mint-trial")

    def test_feedback_requires_sanitization_pinned_citations_and_unchanged_evidence(self):
        path = self.base / "feedback.json"
        write_json(path, {"kind": "change", "stage": "troubleshooting", "summary": "Change", "rollback": "Restore recorded variant"})
        with self.assertRaisesRegex(ExperimentError, "confirm-sanitized"):
            self.manager.feedback("mint-trial", path, False)
        write_json(path, {"kind": "lookup", "stage": "preparation", "summary": "Unpinned citation", "queries": ["fusion"],
                          "source_checks": [{"uri": "upstream://fixture@master/README.md", "url": None,
                              "accessed_at": "2026-10-12", "status": "read", "trust": "accepted_upstream_documented",
                              "claim": "Fusion", "applicability": "related", "comparison": "Version not fixed"}]})
        with self.assertRaises(jsonschema.ValidationError):
            self.manager.feedback("mint-trial", path, True)
        self.lookup_event("preparation")
        self.functional_event()
        self.lookup_event("optimization")
        self.validation_event()
        evidence = self.root / "cases/work-items/mint-trial/measurements.md"
        evidence.write_text("tampered measurements")
        with self.assertRaisesRegex(ExperimentError, "checksum mismatch"):
            self.manager.workflow_check("mint-trial")

    def test_optimization_requires_prior_functional_accuracy_and_final_revalidation(self):
        self.lookup_event("preparation")
        self.lookup_event("optimization")
        self.validation_event()
        gaps = self.manager.workflow_check("mint-trial")["gaps"]
        self.assertIn("functional_and_accuracy_check_must_precede_optimization_lookup", gaps)
        self.lookup_event("optimization")
        self.assertIn("optimization_lookup_must_precede_final_validation", self.manager.workflow_check("mint-trial")["gaps"])
        self.validation_event()
        self.assertTrue(self.manager.workflow_check("mint-trial")["completion_ready"])
        self.feedback_event("change", "optimization", rollback="Restore last reviewed variant")
        self.assertIn("work_after_last_validation_needs_revalidation", self.manager.workflow_check("mint-trial")["gaps"])

    def test_workflow_check_exit_code_distinguishes_missing_evidence_from_ready_for_review(self):
        argv = ["--root", str(self.root), "workflow-check", "--case", "mint-trial"]
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(1, experiments_main(argv))
        self.assertFalse(json.loads(output.getvalue())["completion_ready"])
        self.lookup_event("preparation")
        self.functional_event()
        self.lookup_event("optimization")
        self.validation_event()
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(0, experiments_main(argv))
        self.assertEqual("ready_for_review", json.loads(output.getvalue())["status"])

    def test_submodule_intake_preserves_identity_without_claiming_execution_fingerprint(self):
        module = self.project / "vendor"
        module.mkdir()
        command("git", "init", "-b", "main", cwd=module)
        command("git", "config", "user.name", "Fixture", cwd=module)
        command("git", "config", "user.email", "fixture@example.invalid", cwd=module)
        (module / "source.txt").write_text("original\n")
        command("git", "add", "source.txt", cwd=module)
        command("git", "commit", "-m", "module fixture", cwd=module)
        revision = command("git", "rev-parse", "HEAD", cwd=module)
        command("git", "update-index", "--add", "--cacheinfo", f"160000,{revision},vendor", cwd=self.project)
        (module / "source.txt").write_text("dirty\n")
        with patch.object(self.manager, "source", side_effect=AssertionError("Intake must not fingerprint execution")):
            self.manager.new_case("submodule-trial", self.project, "Nested source", "Intake only", "https://example.invalid/project")
        issue = read_json(self.root / "cases/work-items/submodule-trial/issue.json")
        self.assertEqual("open", issue["state"])
        intake = issue["source"]["intake"]
        self.assertTrue(intake["dirty"])
        self.assertEqual("not_collected", intake["fingerprint_status"])
        self.assertEqual({"path": "vendor", "index_revision": revision, "checkout_revision": revision,
                          "status": "initialized", "dirty": True}, intake["submodules"][0])
        self.ready()
        with self.assertRaisesRegex(ExperimentError, "fingerprint is incomplete"):
            self.planned()
        self.assertEqual(self.before, self.manager.protected())

    def test_uninitialized_gitlink_cannot_escape_execution_fingerprint(self):
        revision = command("git", "rev-parse", "HEAD", cwd=self.project)
        command("git", "update-index", "--add", "--cacheinfo", f"160000,{revision},missing-module", cwd=self.project)
        self.manager.new_case("uninitialized-module", self.project, "Missing module", "Capture missing source", "https://example.invalid/project")
        issue = read_json(self.root / "cases/work-items/uninitialized-module/issue.json")
        self.assertEqual("uninitialized", issue["source"]["intake"]["submodules"][0]["status"])
        with self.assertRaisesRegex(ExperimentError, "Submodule"):
            self.manager.source(self.project)

    def test_optimization_lookup_associated_with_failure_counts_as_error_research(self):
        self.lookup_event("preparation")
        self.functional_event()
        error = self.feedback_event("numerical_issue", "optimization", environment="fixture", error={
            "type": "GradientDifference", "message": "Check measured difference", "expected": "Scoped tolerance", "observed": "Finite deviation"})
        self.lookup_event("optimization", [error["id"]])
        self.validation_event()
        self.feedback_event("resolution", "optimization", resolves=[error["id"]],
                            evidence_refs=["cases/work-items/mint-trial/measurements.md"])
        result = self.manager.workflow_check("mint-trial")
        self.assertTrue(result["completion_ready"])
        self.assertTrue(result["issue_groups"]["target"][0]["source_comparison_recorded"])

    def test_tooling_problem_is_reported_separately_and_is_not_a_migration_edit(self):
        tool_error = self.feedback_event("failure", issue_scope="tooling", environment="fixture", error={
            "type": "MissingDependency", "message": "Recorder import failed", "expected": "Tool starts", "observed": "Import error"})
        self.lookup_event("preparation")
        self.functional_event()
        self.lookup_event("optimization")
        self.validation_event()
        result = self.manager.workflow_check("mint-trial")
        self.assertTrue(result["completion_ready"])
        self.assertIn(tool_error["id"], result["unresolved_events"])
        self.assertEqual([], result["blocking_unresolved_events"])
        self.assertEqual(tool_error["id"], result["issue_groups"]["tooling"][0]["id"])
        self.feedback_event("change", rollback="Revert target edit")
        self.assertIn("work_after_last_validation_needs_revalidation", self.manager.workflow_check("mint-trial")["gaps"])

    def test_preparation_order_uses_target_edits_instead_of_initial_observations(self):
        observed = self.feedback_event("failure", environment="fixture", error={
            "type": "ExistingFailure", "message": "Intake saw an existing error", "expected": "Load", "observed": "Failed before edits"})
        self.lookup_event("preparation")
        self.lookup_event("troubleshooting", [observed["id"]])
        self.functional_event()
        self.lookup_event("optimization")
        self.validation_event()
        self.feedback_event("resolution", resolves=[observed["id"]],
                            evidence_refs=["cases/work-items/mint-trial/measurements.md"])
        self.assertTrue(self.manager.workflow_check("mint-trial")["completion_ready"])
        self.manager.new_case("late-preparation", self.project, "Late preparation", "Record real ordering",
                              "https://example.invalid/model", "npu", ["AnyModel"])
        self.feedback_event("change", case_id="late-preparation", rollback="Restore baseline")
        self.lookup_event("preparation", case_id="late-preparation")
        self.assertIn("preparation_recorded_after_work_started", self.manager.workflow_check("late-preparation")["gaps"])

    def test_tooling_validation_and_lookups_do_not_replace_target_acceptance(self):
        self.lookup_event("preparation")
        self.functional_event()
        self.lookup_event("optimization")
        self.validation_event()
        before = self.manager.workflow_check("mint-trial")
        recorded = self.manager.feedback_events("mint-trial")
        self.feedback_event("lookup", "optimization", issue_scope="tooling", queries=["CLI dependencies"],
                            source_checks=recorded[0]["source_checks"])
        tool_validation = {**recorded[-1]["validation"], "actual_backend": "cpu", "official_weights": False,
                           "accuracy": "not_applicable", "accuracy_protocol": "CLI schema tests only", "optimization": "not_applicable"}
        self.feedback_event("validation", issue_scope="tooling", environment="fixture CPU CLI only", validation=tool_validation,
                            evidence_refs=["cases/work-items/mint-trial/measurements.md"])
        after = self.manager.workflow_check("mint-trial")
        self.assertTrue(after["completion_ready"])
        self.assertEqual(before["checks"], after["checks"])
        self.assertEqual(before["stages"], after["stages"])

    def test_generated_lookup_stdin_and_preflight_do_not_invent_source_reading(self):
        search = {"query": "RMSNorm", "results": [{"uri": "upstream://fixture@" + "a" * 40 + "/README.md",
                   "remote_url": "https://example.invalid/README.md", "revision": "a" * 40,
                   "trust": "accepted_upstream_documented", "title": "RMSNorm implementation"}]}
        output = io.StringIO()
        with patch("sys.stdin", io.StringIO(json.dumps(search))), redirect_stdout(output):
            self.assertEqual(0, experiments_main(["--root", str(self.root), "feedback-draft", "--case", "mint-trial", "--search-results", "-"]))
        draft = json.loads(output.getvalue())
        self.assertTrue(draft["draft"])
        self.assertEqual("not_read", draft["source_checks"][0]["status"])
        self.assertIsNone(draft["source_checks"][0]["accessed_at"])
        self.assertEqual("a" * 40, draft["source_checks"][0]["revision"])
        preflight = io.StringIO()
        with patch("sys.stdin", io.StringIO(json.dumps(draft))), redirect_stdout(preflight):
            self.assertEqual(0, experiments_main(["--root", str(self.root), "feedback-preflight", "--case", "mint-trial", "--file", "-"]))
        self.assertTrue(json.loads(preflight.getvalue())["valid"])
        self.assertEqual([], self.manager.feedback_events("mint-trial"))
        with patch("sys.stdin", io.StringIO(json.dumps(draft))), redirect_stdout(io.StringIO()):
            self.assertEqual(0, experiments_main(["--root", str(self.root), "feedback", "--case", "mint-trial", "--file", "-", "--confirm-sanitized"]))
        result = self.manager.workflow_check("mint-trial")
        self.assertEqual(1, result["draft_events"])
        self.assertIn("preparation_lookup_missing", result["gaps"])
        draft["draft"] = False
        self.manager.feedback("mint-trial", draft, True)
        self.assertIn("preparation_lookup_missing", self.manager.workflow_check("mint-trial")["gaps"])
        draft["source_checks"][0].update(status="read", accessed_at="2026-10-24T00:00:00Z")
        self.manager.feedback("mint-trial", draft, True)
        self.assertIn("preparation_source_body_not_verified", self.manager.workflow_check("mint-trial")["gaps"])
        draft["source_checks"][0]["accessed_at"] = None
        with self.assertRaises(jsonschema.ValidationError):
            self.manager.feedback_preflight("mint-trial", draft)

    def test_preflight_reports_field_path_and_allowed_trust_without_schema_dump(self):
        draft = self.manager.feedback_draft("mint-trial")
        draft["source_checks"][0]["trust"] = "incorrect-trust"
        error = io.StringIO()
        with patch("sys.stdin", io.StringIO(json.dumps(draft))), redirect_stderr(error):
            self.assertEqual(2, experiments_main(["--root", str(self.root), "feedback-preflight", "--case", "mint-trial", "--file", "-"]))
        self.assertIn("$.source_checks[0].trust: allowed values:", error.getvalue())
        self.assertNotIn("Failed validating", error.getvalue())
        self.assertEqual([], self.manager.feedback_events("mint-trial"))

    def test_feedback_preflight_and_append_both_reject_secret_in_event_fields(self):
        draft = self.manager.feedback_draft("mint-trial")
        draft["summary"] = "Fixture credential: " + "hf_" + "x" * 30
        for operation in ("feedback-preflight", "feedback"):
            argv = ["--root", str(self.root), operation, "--case", "mint-trial", "--file", "-"]
            if operation == "feedback":
                argv.append("--confirm-sanitized")
            error = io.StringIO()
            with patch("sys.stdin", io.StringIO(json.dumps(draft))), redirect_stderr(error):
                self.assertEqual(2, experiments_main(argv))
            self.assertIn("Possible credential", error.getvalue())
            self.assertNotIn(draft["summary"], error.getvalue())
        self.assertEqual([], self.manager.feedback_events("mint-trial"))

    def test_scoped_cuda_module_completion_is_not_full_model_migration(self):
        self.manager.new_case("cuda-module", self.project, "CUDA module parity", "Fixed module numerical parity",
                              "https://example.invalid/model", "cuda", ["AnyModel"], task_type="module_validation")
        self.lookup_event("preparation", case_id="cuda-module")
        self.validation_event("troubleshooting", case_id="cuda-module", actual_backend="cuda", official_weights=False,
                              optimization="not_applicable", performance={"metric": "not_applicable", "direction": "lower",
                              "baseline": None, "modified": None, "same_device": False, "protocol": "Module parity task only"})
        result = self.manager.workflow_check("cuda-module")
        self.assertTrue(result["completion_ready"])
        self.assertEqual("not_applicable", result["checks"]["model_migration"])
        self.assertEqual("not_evaluated", result["checks"]["rule_approval"])
        self.assertEqual("pending_validation", result["generalization"])

    def test_investigation_can_finish_without_falsely_claiming_speedup(self):
        self.manager.new_case("optimization-study", self.project, "Optimization study", "Measure candidate effect",
                              "https://example.invalid/model", "npu", ["AnyModel"], task_type="optimization_investigation")
        self.lookup_event("preparation", case_id="optimization-study")
        self.functional_event(case_id="optimization-study")
        self.lookup_event("optimization", case_id="optimization-study")
        self.validation_event(case_id="optimization-study", official_weights=False, optimization="no_gain", performance={
            "metric": "step_seconds", "direction": "lower", "baseline": 2.0, "modified": 2.0,
            "same_device": True, "protocol": "Fixed local device, repeated synchronized measurements"})
        result = self.manager.workflow_check("optimization-study")
        self.assertTrue(result["completion_ready"])
        self.assertEqual("investigated", result["checks"]["optimization_goal"])
        self.assertEqual("not_applicable", result["checks"]["model_migration"])
        self.validation_event(case_id="optimization-study", accuracy="pending", optimization="no_gain")
        result = self.manager.workflow_check("optimization-study")
        self.assertFalse(result["completion_ready"])
        self.assertEqual("pending", result["checks"]["optimization_goal"])

    def test_tooling_scope_accepts_command_evidence_without_model_accuracy_claim(self):
        self.manager.new_case("tooling-repair", self.project, "Tool integration", "CLI schema test succeeds",
                              "https://example.invalid/tool", "cpu", ["not_a_model"], task_type="tooling")
        self.assertEqual("tooling", self.manager.feedback_draft("tooling-repair")["issue_scope"])
        observed = self.feedback_event("failure", case_id="tooling-repair", issue_scope="tooling", environment="fixture", error={
            "type": "DependencyMissing", "message": "Tool cannot import", "expected": "Command starts", "observed": "Import failed"})
        self.lookup_event("preparation", case_id="tooling-repair")
        self.lookup_event("troubleshooting", [observed["id"]], case_id="tooling-repair")
        self.validation_event("troubleshooting", case_id="tooling-repair", actual_backend="cpu", official_weights=False,
                              finite_outputs=False, accuracy="not_applicable", accuracy_protocol="CLI integration assertions; no model numerics",
                              optimization="not_applicable")
        result = self.manager.workflow_check("tooling-repair")
        self.assertIn(observed["id"], result["blocking_unresolved_events"])
        self.feedback_event("resolution", case_id="tooling-repair", issue_scope="tooling", resolves=[observed["id"]],
                            evidence_refs=["cases/work-items/tooling-repair/measurements.md"])
        result = self.manager.workflow_check("tooling-repair")
        self.assertTrue(result["completion_ready"])
        self.assertEqual("not_applicable", result["checks"]["model_migration"])
        self.assertEqual(self.before, self.manager.protected())


if __name__ == "__main__":
    unittest.main()
