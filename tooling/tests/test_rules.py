import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from n2s_rules.engine import EngineError, apply_plan, create_plan, inspect_project, rollback_report
from n2s_rules.plugins import load_rule_plugins
from n2s_rules.registry import validate_registry


N2S_ROOT = Path(__file__).resolve().parents[2]
RULES_ROOT = N2S_ROOT / "rules"
MINT_ROOT = N2S_ROOT / "cases" / "MINT"


class RuleFixtureTests(unittest.TestCase):
    def test_registry_and_all_fixtures(self):
        registry, packages = validate_registry(RULES_ROOT)
        self.assertEqual(3, len(packages))
        self.assertEqual(0, registry["approved_rule_count"])

    def test_candidate_plan_is_review_only_and_apply_refuses(self):
        _, packages = validate_registry(RULES_ROOT)
        package = RULES_ROOT / "pytorch.npu.sinusoidal-fp64-fallback"
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            project.mkdir()
            shutil.copy2(package / "fixtures/before.py", project / "model.py")
            inspection = inspect_project(project, packages)
            self.assertEqual(1, len(inspection["findings"]))
            plan = create_plan(
                project,
                RULES_ROOT,
                packages,
                rule_ids=["pytorch.npu.sinusoidal-fp64-fallback"],
                include_candidates=True,
            )
            self.assertEqual(1, len(plan["changes"]))
            self.assertFalse(plan["changes"][0]["eligible_for_apply"])
            plan_path = Path(temporary) / "plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaisesRegex(EngineError, "not approved"):
                apply_plan(plan_path, packages, RULES_ROOT)
            self.assertEqual((package / "fixtures/before.py").read_text(), (project / "model.py").read_text())

    def test_recovered_upstream_mint_detects_exact_three_candidates(self):
        _, packages = validate_registry(RULES_ROOT)
        snapshot = MINT_ROOT / "sources" / "ascend-v043" / "lerobot_policy_mint" / "src" / "lerobot_policy_mint" / "modeling_mint.py"
        exact_patch = MINT_ROOT / "comparisons" / "patches" / "supplemental-official-declared-59fa23d_vs_ascend-v043-package.patch"
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            model_dir = project / "lerobot_policy_mint"
            model_dir.mkdir(parents=True)
            shutil.copy2(snapshot, model_dir / "modeling_mint.py")
            subprocess.run(
                ["patch", "-R", "-s", "-p4"],
                cwd=project,
                input=exact_patch.read_text(),
                text=True,
                check=True,
                capture_output=True,
            )
            inspection = inspect_project(project, packages)
            expected = {
                "pytorch.npu.sinusoidal-fp64-fallback",
                "pytorch.npu.compile-capability-fallback",
                "pytorch.attention.cache-dtype-alignment",
            }
            self.assertEqual(expected, {finding["rule_id"] for finding in inspection["findings"]})
            self.assertEqual(3, len(inspection["findings"]))
            candidate = create_plan(project, RULES_ROOT, packages, include_candidates=True)
            self.assertEqual(3, len(candidate["changes"]))
            self.assertFalse(any(change["eligible_for_apply"] for change in candidate["changes"]))
            approved = create_plan(project, RULES_ROOT, packages)
            self.assertEqual([], approved["changes"])

    def test_external_snapshot_rule_matrix_fails_closed(self):
        _, packages = validate_registry(RULES_ROOT)
        by_id = {package.manifest["id"]: package for package in packages}
        projects = N2S_ROOT / "cases" / "validation-projects"
        lerobot = inspect_project(projects / "lerobot-4aaff99", packages)
        openpi = inspect_project(projects / "openpi-215abfb", packages)

        def counts(report):
            result = {}
            for finding in report["findings"]:
                result[finding["rule_id"]] = result.get(finding["rule_id"], 0) + 1
            return result

        self.assertEqual(
            {
                "pytorch.attention.cache-dtype-alignment": 1,
                "pytorch.npu.compile-capability-fallback": 2,
                "pytorch.npu.sinusoidal-fp64-fallback": 1,
            },
            counts(lerobot),
        )
        self.assertEqual(
            {
                "pytorch.attention.cache-dtype-alignment": 1,
                "pytorch.npu.sinusoidal-fp64-fallback": 1,
            },
            counts(openpi),
        )
        self.assertFalse(
            any(finding["rule_id"] == "pytorch.npu.compile-capability-fallback" for finding in openpi["findings"])
        )
        fp64 = by_id["pytorch.npu.sinusoidal-fp64-fallback"]
        plugins = load_rule_plugins(fp64.package, fp64.manifest)
        for project, relative, expected_adapter, expected_text in (
            (
                projects / "lerobot-4aaff99",
                "src/lerobot/utils/device_utils.py",
                "lerobot-shared-safe-dtype",
                'if device in {"mps", "npu"} and dtype == torch.float64:',
            ),
            (
                projects / "openpi-215abfb",
                "src/openpi/models_pytorch/pi0_pytorch.py",
                "openpi-local-safe-dtype",
                'if device_type == "npu" and target_dtype == torch.float64:',
            ),
        ):
            source = (project / relative).read_text(encoding="utf-8")
            findings = plugins["detector"].detect(source, relative)
            self.assertEqual([expected_adapter], [finding["metadata"]["adapter"] for finding in findings])
            after = plugins["codemod"].transform(source, relative, findings)
            self.assertIn(expected_text, after)
            self.assertEqual([], plugins["validator"].validate_after(source, after, relative, findings))
            self.assertEqual([], plugins["detector"].detect(after, relative))

    def test_fp64_external_adapter_fixtures(self):
        _, packages = validate_registry(RULES_ROOT)
        package = next(item for item in packages if item.manifest["id"] == "pytorch.npu.sinusoidal-fp64-fallback")
        plugins = load_rule_plugins(package.package, package.manifest)
        fixtures = package.package / "fixtures"
        for name, path in (
            ("lerobot", "src/lerobot/utils/device_utils.py"),
            ("openpi", "src/openpi/models_pytorch/pi0_pytorch.py"),
        ):
            before = (fixtures / f"{name}_before.py").read_text(encoding="utf-8")
            expected = (fixtures / f"{name}_after.py").read_text(encoding="utf-8")
            findings = plugins["detector"].detect(before, path)
            self.assertEqual(1, len(findings))
            self.assertEqual(expected, plugins["codemod"].transform(before, path, findings))

    def test_approved_transaction_and_rollback_in_isolated_registry(self):
        rule_id = "pytorch.npu.sinusoidal-fp64-fallback"
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            rules_root = temporary / "rules"
            shutil.copytree(RULES_ROOT, rules_root)
            manifest_path = rules_root / rule_id / "manifest.yaml"
            manifest = yaml.safe_load(manifest_path.read_text())
            manifest["status"] = "approved"
            manifest["automation"]["auto_apply"] = True
            manifest["promotion"]["blockers"] = []
            manifest["verification"]["commands"] = [["python", "-c", "import pathlib; compile(pathlib.Path('model.py').read_text(), 'model.py', 'exec')"]]
            manifest["approval"] = {
                "approver": "isolated-test-only",
                "approved_at": "2026-08-31T00:00:00+00:00",
                "evidence_revision": "test-fixture",
                "evidence_level": "integration",
                "scope": "temporary unit test",
                "limitations": ["not production evidence"],
            }
            manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
            _, packages = validate_registry(rules_root, write=True)
            project = temporary / "project"
            project.mkdir()
            before = (rules_root / rule_id / "fixtures/before.py").read_text()
            after = (rules_root / rule_id / "fixtures/after.py").read_text()
            (project / "model.py").write_text(before)
            plan = create_plan(project, rules_root, packages, rule_ids=[rule_id])
            plan_path = temporary / "approved-plan.json"
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            report, report_path = apply_plan(plan_path, packages, rules_root)
            self.assertEqual("applied", report["status"])
            self.assertEqual(after, (project / "model.py").read_text())
            (project / "model.py").write_text(after + "# post-apply user edit\n")
            with self.assertRaisesRegex(EngineError, "post-apply edits"):
                rollback_report(report_path)
            self.assertTrue((project / "model.py").read_text().endswith("# post-apply user edit\n"))
            (project / "model.py").write_text(after)
            rolled_back = rollback_report(report_path)
            self.assertEqual("rolled_back", rolled_back["status"])
            self.assertEqual(before, (project / "model.py").read_text())

            manifest = yaml.safe_load(manifest_path.read_text())
            manifest["verification"]["commands"] = [["python", "-c", "raise SystemExit(7)"]]
            manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
            _, packages = validate_registry(rules_root, write=True)
            failed_plan = create_plan(project, rules_root, packages, rule_ids=[rule_id])
            failed_plan_path = temporary / "failed-plan.json"
            failed_plan_path.write_text(json.dumps(failed_plan), encoding="utf-8")
            failed_report_path = temporary / "failed-report.json"
            with self.assertRaisesRegex(EngineError, "verification command failed"):
                apply_plan(failed_plan_path, packages, rules_root, report_path=failed_report_path)
            self.assertEqual(before, (project / "model.py").read_text())
            self.assertEqual("rolled_back_on_failure", json.loads(failed_report_path.read_text())["status"])


if __name__ == "__main__":
    unittest.main()
