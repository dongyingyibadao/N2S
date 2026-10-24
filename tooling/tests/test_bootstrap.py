"""CPU-only coverage for startup before optional tool packages can be imported."""

import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import venv


TOOLING = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("n2s_bootstrap_test_subject", TOOLING / "bootstrap.py")
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


class BootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.temp.name)
        cls.env = cls.directory / "tool env"
        venv.EnvBuilder(with_pip=False).create(cls.env)
        cls.python = cls.env / "bin/python"

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def launch(self, tool, *args, environment=None, cwd=None):
        env = dict(os.environ, N2S_PYTHON=str(self.python))
        if environment:
            env.update(environment)
        return subprocess.run([str(TOOLING / ("n2s-" + tool)), *args], env=env,
                              cwd=cwd or self.directory, capture_output=True, text=True, timeout=20)

    def test_explicit_interpreter_doctor_reports_missing_packages_without_importing_project(self):
        shadow = self.directory / "shadow"
        shadow.mkdir(exist_ok=True)
        marker = self.directory / "must-not-exist"
        for name in ("json", "jsonschema", "torch", "sitecustomize"):
            (shadow / (name + ".py")).write_text(
                "from pathlib import Path\nPath(" + repr(str(marker)) + ").write_text('executed')\nraise RuntimeError('project imported')\n")
        result = self.launch("knowledge", "doctor", "--json", environment={"PYTHONPATH": str(shadow)}, cwd=shadow)
        self.assertEqual(2, result.returncode, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(str(self.python), value["interpreter"])
        self.assertEqual(["jsonschema"], value["missing"])
        self.assertEqual("3.10", value["python"]["minimum"])
        self.assertIn("path", value["git"])
        self.assertIn("N2S_PYTHON", " ".join(value["setup"]["manual_commands"]))
        self.assertFalse(value["ready"])
        self.assertFalse(marker.exists())

    def test_missing_dependencies_have_actionable_error_and_help(self):
        for tool in bootstrap.TOOLS:
            with self.subTest(tool=tool):
                result = self.launch(tool, "status")
                self.assertEqual(2, result.returncode)
                self.assertIn("missing N2S tool dependencies", result.stderr)
                self.assertIn(str(self.python), result.stderr)
                self.assertIn("jsonschema", result.stderr)
                self.assertIn("N2S_PYTHON", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                help_result = self.launch(tool, "--help")
                self.assertEqual(0, help_result.returncode)
                self.assertIn("usage: n2s-" + tool, help_result.stdout)
                self.assertIn("doctor", help_result.stdout)
                self.assertNotIn("Traceback", help_result.stderr)

    def test_unavailable_explicit_interpreter_does_not_fall_back(self):
        result = self.launch("knowledge", "doctor", environment={"N2S_PYTHON": str(self.directory / "missing-python")})
        self.assertEqual(2, result.returncode)
        self.assertIn("interpreter not found", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_metadata_probe_never_imports_optional_packages(self):
        with patch.object(bootstrap.importlib, "import_module", side_effect=AssertionError("unexpected import")):
            value = bootstrap.report("knowledge", check_git=False)
        self.assertEqual(["jsonschema"], [item["name"] for item in value["packages"]])
        self.assertIsNone(value["git"])

    def test_ready_startup_preserves_argv_and_exit_status(self):
        cli = unittest.mock.Mock()
        cli.main.return_value = 7
        ready = {"ready": True}
        with patch.object(bootstrap.sys, "path", bootstrap.sys.path.copy()), patch.object(bootstrap, "report", return_value=ready), patch.object(bootstrap.importlib, "import_module", return_value=cli):
            self.assertEqual(7, bootstrap.main(["experiments", "workflow-check", "--case", "trial"]))
        cli.main.assert_called_once_with(["workflow-check", "--case", "trial"])

    def test_transitive_import_failure_has_no_raw_traceback(self):
        value = bootstrap.report("knowledge", check_git=False)
        value["ready"] = True
        stderr = io.StringIO()
        with patch.object(bootstrap.sys, "path", bootstrap.sys.path.copy()), patch.object(bootstrap, "report", return_value=value), patch.object(bootstrap.importlib, "import_module", side_effect=ModuleNotFoundError("missing", name="referencing")), contextlib.redirect_stderr(stderr):
            self.assertEqual(2, bootstrap.main(["knowledge", "status"]))
        self.assertIn("referencing", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_version_difference_is_visible_without_changing_command_eligibility(self):
        with patch.object(bootstrap.importlib.metadata, "version", return_value="0.0.fixture"):
            value = bootstrap.report("knowledge", check_git=False)
        self.assertTrue(value["ready"])
        self.assertEqual(["jsonschema"], value["version_warnings"])


if __name__ == "__main__":
    unittest.main()
