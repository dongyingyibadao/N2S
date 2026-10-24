"""Standard-library bootstrap for repository tools; never install or probe devices."""

import argparse
import importlib
import importlib.metadata
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys


TOOLING = Path(__file__).resolve().parent
MIN_PYTHON = (3, 10)
TOOLS = {
    "knowledge": ("n2s_knowledge.cli", ("jsonschema",)),
    "experiments": ("n2s_experiments.cli", ("jsonschema",)),
    "rules": ("n2s_rules.cli", ("libcst", "PyYAML", "jsonschema")),
}


def dependency_report(tool):
    """Read installed distribution metadata without importing any third-party code."""
    pins = {}
    for line in (TOOLING / "requirements.txt").read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"\s*([A-Za-z0-9_.-]+)==([^\s;]+)\s*", line)
        if match:
            pins[match.group(1).lower()] = match.group(2)
    packages = []
    for name in TOOLS[tool][1]:
        try:
            installed = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            installed = None
        required = pins[name.lower()]
        packages.append({"name": name, "required_version": required, "installed_version": installed,
                         "available": installed is not None, "version_matches": installed == required})
    return packages


def git_report():
    executable = shutil.which("git")
    report = {"path": executable, "available": False, "version": None, "error": None}
    if not executable:
        report["error"] = "Git executable not found on PATH"
        return report
    try:
        result = subprocess.run([executable, "--version"], capture_output=True, text=True,
                                timeout=5, check=True)
        report.update(available=True, version=result.stdout.strip())
    except (OSError, subprocess.SubprocessError) as error:
        report["error"] = "Git version check failed: " + type(error).__name__
    return report


def report(tool, check_git=True):
    packages = dependency_report(tool)
    missing = [package["name"] for package in packages if not package["available"]]
    compatible = sys.version_info[:2] >= MIN_PYTHON
    git = git_report() if check_git else None
    tool_env = TOOLING.parent / ".venv"
    python = tool_env / "bin/python"
    command = TOOLING / ("n2s-" + tool)
    requirements = TOOLING / "requirements.txt"
    # These are suggestions only; no bootstrap path installs or changes an environment.
    manual_commands = [
        "python3 -m venv " + shlex.quote(str(tool_env)),
        shlex.quote(str(python)) + " -m pip install -r " + shlex.quote(str(requirements)),
        "N2S_PYTHON=" + shlex.quote(str(python)) + " " + shlex.quote(str(command)) + " doctor --json",
    ]
    return {
        "tool": "n2s-" + tool, "interpreter": sys.executable,
        "python": {"version": ".".join(map(str, sys.version_info[:3])), "minimum": "3.10", "compatible": compatible},
        "git": git, "packages": packages, "missing": missing,
        "version_warnings": [package["name"] for package in packages
                             if package["available"] and not package["version_matches"]],
        "ready": compatible and not missing and (git is None or git["available"]),
        "setup": {"interpreter_variable": "N2S_PYTHON", "requirements": str(requirements),
                  "manual_commands": manual_commands,
                  "note": "Use a separate trusted tool environment. Setup commands are manual; model environments are not modified."},
    }


def print_report(value, stream=None):
    stream = stream or sys.stdout
    print("tool: " + value["tool"], file=stream)
    print("interpreter: " + value["interpreter"], file=stream)
    print("Python: " + value["python"]["version"] + " (requires >=3.10)", file=stream)
    if value["git"] is not None:
        git = value["git"]
        print("Git: " + (git["version"] or git["error"] or "unavailable"), file=stream)
    for package in value["packages"]:
        status = package["installed_version"] or "MISSING"
        print(package["name"] + ": " + status + " (pinned " + package["required_version"] + ")", file=stream)
    if value["version_warnings"]:
        print("warning: package versions differ from tooling/requirements.txt; existing command behavior is retained", file=stream)
    print(value["setup"]["note"], file=stream)
    for command in value["setup"]["manual_commands"]:
        print("  " + command, file=stream)


def startup_error(value, import_error=None):
    if import_error is not None:
        name = getattr(import_error, "name", None) or type(import_error).__name__
        print("error: cannot import an N2S tool dependency: " + name, file=sys.stderr)
    elif not value["python"]["compatible"]:
        print("error: N2S tools require Python 3.10 or newer", file=sys.stderr)
    else:
        print("error: missing N2S tool dependencies: " + ", ".join(value["missing"]), file=sys.stderr)
    print_report(value, sys.stderr)
    print("Select a trusted interpreter with N2S_PYTHON; doctor --json needs only the standard library.", file=sys.stderr)


def fallback_help(tool, value):
    print("usage: n2s-" + tool + " COMMAND [OPTIONS]")
    print("\nBootstrap command: doctor [--json] (standard library only; no installation or device probe)")
    print("Set N2S_PYTHON=/absolute/path/to/tool-env/bin/python to select the tool interpreter.")
    print("\nFull command help requires the tool dependencies. Current startup diagnosis:")
    print_report(value)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in TOOLS:
        print("error: bootstrap expects knowledge, experiments or rules", file=sys.stderr)
        return 2
    tool, args = argv[0], argv[1:]
    if args[:1] == ["doctor"]:
        parser = argparse.ArgumentParser(prog="n2s-" + tool + " doctor",
                                         description="Read-only tool dependency diagnosis; no model imports or installation")
        parser.add_argument("--json", action="store_true")
        parsed = parser.parse_args(args[1:])
        value = report(tool)
        if parsed.json:
            print(json.dumps(value, indent=2, sort_keys=True))
        else:
            print_report(value)
        return 0 if value["ready"] else 2

    value = report(tool, check_git=False)
    if not value["ready"]:
        if "--help" in args or "-h" in args:
            fallback_help(tool, value)
            return 0
        startup_error(value)
        return 2
    # Isolated Python excludes the caller's checkout/PYTHONPATH. Add only trusted N2S sources.
    sys.path.insert(0, str(TOOLING / "src"))
    try:
        cli = importlib.import_module(TOOLS[tool][0])
    except ImportError as error:
        startup_error(value, error)
        return 2
    return cli.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
