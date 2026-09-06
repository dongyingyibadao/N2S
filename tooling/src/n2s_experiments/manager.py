import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import uuid
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[3]
IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9-]{2,79}\Z")
SECRET = re.compile(r"-----BEGIN .*PRIVATE KEY-----|\b(?:gh[pousr]_[A-Za-z0-9]{20,}|hf_[A-Za-z0-9]{20,})|https?://[^\s/@]+:[^\s/@]+@|(?:api[_-]?key|access[_-]?token|password)\s*[:=]\s*[\"']?[^\s\"']{8,}", re.I)


class ExperimentError(ValueError):
    pass


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def encoded(value):
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def file_hash(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def git(project, *args):
    result = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", *args], cwd=project,
                            capture_output=True, check=True, timeout=30)
    output = result.stdout.decode("utf-8")
    return output if "-z" in args else output.strip()


def check_text(text):
    if SECRET.search(text):
        raise ExperimentError("Possible credential in record; redact before saving or publishing")


def identifier(value):
    if not IDENTIFIER.fullmatch(value):
        raise ExperimentError(f"Invalid identifier: {value!r}")
    return value


def probe(python=sys.executable):
    # Isolated interpreter excludes the target checkout and upstream snapshots from sys.path.
    script = '''
import importlib.metadata as m, json, os, platform
r = {"python": platform.python_version(), "versions": {}, "devices": [{"backend": "cpu", "name": platform.machine(), "index": 0}], "errors": [], "visibility": {k: os.environ.get(k) for k in ("CUDA_VISIBLE_DEVICES", "ASCEND_RT_VISIBLE_DEVICES", "ASCEND_DEVICE_ID")}}
for name in ("torch", "torch-npu", "triton", "transformers", "lerobot"):
    try: r["versions"][name] = m.version(name)
    except m.PackageNotFoundError: pass
r["versions"]["python"] = r["python"]
try:
    import torch
    r["versions"]["cuda_runtime"] = str(torch.version.cuda)
    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()): r["devices"].append({"backend": "cuda", "name": torch.cuda.get_device_name(i), "index": i})
except Exception as e: r["errors"].append("torch: " + type(e).__name__)
try:
    import torch_npu
    import torch
    if torch.npu.is_available():
        for i in range(torch.npu.device_count()): r["devices"].append({"backend": "npu", "name": torch.npu.get_device_name(i), "index": i})
except Exception as e: r["errors"].append("torch_npu: " + type(e).__name__)
print(json.dumps(r))
'''
    executable = str(Path(python).absolute())
    result = subprocess.run([executable, "-I", "-c", script], cwd="/tmp", capture_output=True,
                            text=True, timeout=45, check=True)
    # Some installed accelerator packages print initialization notices to stdout.
    value = json.loads(result.stdout.splitlines()[-1])
    value["interpreter"] = executable
    value["hardware_reports"] = {}
    for name, argv in (
        ("nvidia", ["nvidia-smi", "--query-gpu=uuid,name,driver_version,memory.total", "--format=csv,noheader"]),
        ("ascend", ["npu-smi", "info", "-t", "board", "-i", "0"]),
    ):
        if shutil.which(argv[0]):
            try:
                report = subprocess.run(argv, capture_output=True, text=True, timeout=10)
                value["hardware_reports"][name] = report.stdout.strip() if report.returncode == 0 else "not_available"
            except subprocess.TimeoutExpired:
                value["hardware_reports"][name] = "probe_timeout"
    value["versions"]["cann"] = "not_available"
    for version_file in (Path("/usr/local/Ascend/ascend-toolkit/latest/version.cfg"),
                         Path("/usr/local/Ascend/ascend-toolkit/latest/version.info")):
        if version_file.is_file():
            for line in version_file.read_text(errors="replace").splitlines():
                if line.startswith("version="):
                    value["versions"]["cann"] = line.partition("=")[2].strip()
    return value


class Experiments:
    def __init__(self, root=ROOT, probe_fn=probe):
        self.root = Path(root).resolve()
        self.probe = probe_fn

    def path(self, relative):
        path = self.root / relative
        if not path.resolve().is_relative_to(self.root):
            raise ExperimentError("Path escapes N2S")
        for parent in (path, *path.parents):
            if parent == self.root:
                break
            if parent.is_symlink():
                raise ExperimentError(f"Symlinks are not allowed: {relative}")
        return path

    def write(self, relative, value):
        if not str(relative).startswith(("cases/work-items/", "evaluations/_local/")):
            raise ExperimentError("Experiment writes are restricted to cases/work-items and local cache")
        path = self.path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(encoded(value))
        return path

    def validate_data(self, kind, value):
        schema = read_json(self.path(f"evaluations/schemas/{kind}.schema.json"))
        jsonschema.Draft202012Validator(schema).validate(value)
        check_text(encoded(value).decode())

    def task(self, key):
        parts = key.split("/")
        if len(parts) != 2:
            raise ExperimentError("Task must be CASE_ID/TASK_ID")
        case_id, task_id = map(identifier, parts)
        value = read_json(self.path(f"cases/work-items/{case_id}/tasks/{task_id}.json"))
        self.validate_data("task", value)
        if value["case_id"] != case_id or value["id"] != task_id:
            raise ExperimentError("Task ID does not match path")
        return value

    def source(self, project):
        project = Path(project).resolve()
        if project.is_relative_to(self.root) or self.root.is_relative_to(project):
            raise ExperimentError("Use a separate external Git checkout, never an N2S snapshot")
        if Path(git(project, "rev-parse", "--show-toplevel")).resolve() != project:
            raise ExperimentError("Project must be the external Git repository root")
        # Include nonignored untracked files so a new helper also invalidates an old plan.
        names = git(project, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0")
        files = {}
        for name in sorted(set(filter(None, names))):
            path = project / name
            if path.is_symlink():
                if not path.resolve().is_relative_to(project):
                    raise ExperimentError("Nonignored source symlinks must remain inside the project")
                files[name] = {"symlink": os.readlink(path)}
            elif path.is_file():
                files[name] = file_hash(path)
            elif path.is_dir():
                raise ExperimentError("Submodule checkouts need a separate explicitly pinned task")
            else:
                files[name] = "deleted"
        return {"revision": git(project, "rev-parse", "HEAD"), "tree_sha256": digest(files),
                "dirty": bool(git(project, "status", "--porcelain")), "files": files}

    def protected(self):
        return self.fingerprint(("rules", "reviews/candidate-rules"))

    def fingerprint(self, relatives):
        files = {}
        for relative in relatives:
            directory = self.path(relative)
            paths = [directory] if directory.is_file() else sorted(directory.rglob("*"))
            for path in paths:
                if "__pycache__" in path.parts or path.suffix == ".pyc":
                    continue
                if path.is_symlink():
                    files[str(path.relative_to(self.root))] = {"symlink": os.readlink(path)}
                elif path.is_file():
                    files[str(path.relative_to(self.root))] = {"sha256": file_hash(path), "mode": path.stat().st_mode}
        return digest(files)

    def workflow(self):
        return self.fingerprint(("tooling/n2s-experiments", "tooling/src/n2s_experiments", "evaluations/schemas"))

    def new_case(self, case_id, project, title, goal, source_url, backend="npu", models=None):
        identifier(case_id)
        source = self.source(project)
        issue = {"schema_version": "1.0.0", "id": case_id, "title": title, "created_at": now(),
                 "state": "open", "generalization": "pending_validation", "models": models or ["unspecified"],
                 "source": {"url": source_url, "baseline_revision": source["revision"]},
                 "goal": goal,
                 "observations": "Intake checkout is dirty; baseline_revision identifies HEAD, not the executed variant." if source["dirty"] else "",
                 "knowledge_refs": [], "related_rules": []}
        task = {"schema_version": "1.0.0", "id": "reproduce", "case_id": case_id,
                "title": title, "state": "draft", "claim": goal, "level": "observation",
                "requirements": {"backends": [backend], "device_name_contains": [], "versions": {}},
                "depends_on": [], "evidence_refs": [], "protocol": {
                    "input_description": "pending: fixed input and observed failure stage",
                    "seed": None, "assets": [], "variant": "baseline",
                    "acceptance": "pending: user must define what counts as running successfully",
                    "comparison_key": case_id}, "execution": None}
        self.validate_data("issue", issue)
        self.validate_data("task", task)
        case_path = self.path(f"cases/work-items/{case_id}")
        if case_path.exists():
            raise ExperimentError("Case already exists; use a new ID")
        self.write(f"cases/work-items/{case_id}/issue.json", issue)
        self.write(f"cases/work-items/{case_id}/tasks/reproduce.json", task)
        return {"case": str(case_path), "task": f"{case_id}/reproduce", "state": "draft"}

    def runs(self, case_id):
        return sorted(self.path(f"cases/work-items/{identifier(case_id)}/runs").glob("*/run.json"))

    def case_models(self, case_id):
        issue = read_json(self.path(f"cases/work-items/{identifier(case_id)}/issue.json"))
        self.validate_data("issue", issue)
        if issue["id"] != case_id:
            raise ExperimentError("Case ID mismatch")
        return sorted(issue["models"])

    def accepted_runs(self, key, task):
        results = []
        models = self.case_models(task["case_id"])
        for path in self.runs(task["case_id"]):
            _, run = self.checked_run(path)
            review_path = path.with_name("review.json")
            if (run["task"] != key or run["task_sha256"] != digest(task)
                    or run["models"] != models or not review_path.exists()):
                continue
            review = read_json(review_path)
            self.validate_data("review", review)
            if review["run_sha256"] == digest(run) and review["conclusion"] == "meets_task_acceptance":
                self.check_acceptance(run)
                results.append(run)
        return results

    def blockers(self, key, task, environment):
        reasons = []
        if task["state"] != "ready":
            reasons.append("task_" + task["state"])
        devices = [d for d in environment["devices"] if d["backend"] in task["requirements"]["backends"]]
        names = task["requirements"]["device_name_contains"]
        if names:
            devices = [d for d in devices if any(name.lower() in d["name"].lower() for name in names)]
        if not devices:
            reasons.append("hardware_mismatch")
        for package, expected in task["requirements"]["versions"].items():
            if environment["versions"].get(package) != expected:
                reasons.append("version_mismatch:" + package)
        for dependency in task["depends_on"]:
            dep = self.task(dependency)
            if not self.accepted_runs(dependency, dep):
                reasons.append("dependency_pending:" + dependency)
        if "pending:" in encoded(task["protocol"]).decode().lower():
            reasons.append("protocol_pending")
        return reasons

    def queue(self, backend="auto", python=sys.executable, model=None):
        environment = self.probe(python) if backend == "auto" else None
        rows = []
        for path in sorted(self.path("cases/work-items").glob("*/tasks/*.json")):
            key = path.parent.parent.name + "/" + path.stem
            task = self.task(key)
            models = self.case_models(task["case_id"])
            if model is not None and model.casefold() not in {name.casefold() for name in models}:
                continue
            if backend != "auto" and backend not in task["requirements"]["backends"]:
                continue
            records = [read_json(p) for p in self.runs(task["case_id"]) if read_json(p)["task"] == key]
            rows.append({"task": key, "title": task["title"], "state": task["state"], "models": models,
                         "requirements": task["requirements"], "runs": len(records),
                         "history": [{"id": r["id"], "status": r["status"], "finished_at": r["finished_at"],
                                      "models": r["models"],
                                      "matches_current_task": r["task_sha256"] == digest(task) and r["models"] == models,
                                      "summary": r["summary"]} for r in records],
                         "accepted_runs": len(self.accepted_runs(key, task)),
                         "blockers": self.blockers(key, task, environment) if environment else ["host_not_probed"],
                         "note": "Prior runs are evidence, not approval or coverage of every host"})
        return {"environment": environment, "tasks": rows}

    def plan(self, key, project, python=sys.executable):
        task = self.task(key)
        environment = self.probe(python)
        blockers = self.blockers(key, task, environment)
        if blockers:
            raise ExperimentError("Not runnable: " + ", ".join(blockers))
        project = Path(project).resolve()
        source = self.source(project)
        argv = [str(Path(python).absolute()) if arg == "{python}" else arg for arg in task["execution"]["argv"]]
        plan = {"task": key, "task_snapshot": task, "task_sha256": digest(task),
                "models": self.case_models(task["case_id"]),
                "project": str(project), "python": str(Path(python).absolute()), "source": source,
                "assets": self.check_assets(task, project),
                "environment": environment, "rules_sha256": self.protected(),
                "workflow_sha256": self.workflow(),
                "n2s_revision": git(self.root, "rev-parse", "HEAD"), "argv": argv,
                "execution": task["execution"], "created_at": now(),
                "previous_matching_runs": [r["id"] for r in self.accepted_runs(key, task)
                                           if r["source"] == source and r["environment"] == environment]}
        check_text(encoded(plan).decode())
        token = digest(plan)
        path = self.write(f"evaluations/_local/plans/{token}.json", plan)
        return {"plan": str(path), "approval_token": token, "details": plan,
                "warning": "Review the full argv and resource costs. This is not a sandbox. Exit 0 is not model validation."}

    def run(self, plan_path, approval, repeat_reason=None):
        path = Path(plan_path).resolve()
        if path.parent != self.path("evaluations/_local/plans"):
            raise ExperimentError("Run only a locally generated plan")
        plan = read_json(path)
        if digest(plan) != approval or path.stem != approval:
            raise ExperimentError("Explicit approval must equal the unmodified plan SHA256")
        lock_path = self.path("evaluations/_local/run.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ExperimentError("Another experiment is running in this checkout") from error
            consumed = self.path(f"evaluations/_local/consumed/{approval}.json")
            if consumed.exists():
                raise ExperimentError("Approval was already consumed; generate and confirm a new plan")
            task = self.task(plan["task"])
            if self.workflow() != plan["workflow_sha256"] or git(self.root, "rev-parse", "HEAD") != plan["n2s_revision"]:
                raise ExperimentError("N2S runner or revision changed; re-plan")
            if digest(task) != plan["task_sha256"] or task != plan["task_snapshot"]:
                raise ExperimentError("Task changed after approval")
            if self.case_models(task["case_id"]) != plan["models"]:
                raise ExperimentError("Case model scope changed; re-plan")
            environment = self.probe(plan["python"])
            if environment != plan["environment"] or self.blockers(plan["task"], task, environment):
                raise ExperimentError("Environment or dependency evidence changed; re-plan")
            if self.source(plan["project"]) != plan["source"] or self.protected() != plan["rules_sha256"]:
                raise ExperimentError("Source or protected rules changed; re-plan")
            if self.check_assets(task, Path(plan["project"])) != plan["assets"]:
                raise ExperimentError("Asset drift; re-plan")
            if plan["previous_matching_runs"] and not repeat_reason:
                raise ExperimentError("Matching reviewed evidence exists; provide an explicit repeat reason")
            self.write(f"evaluations/_local/consumed/{approval}.json", {"consumed_at": now(), "repeat_reason": repeat_reason})
            return self._execute(plan, approval)

    def _execute(self, plan, approval):
        run_id = "run-" + uuid.uuid4().hex
        log = self.path(f"evaluations/_local/logs/{run_id}.log")
        log.parent.mkdir(parents=True, exist_ok=True)
        started = now()
        status, code = "command_failed", None
        with log.open("xb") as output:
            process = None
            try:
                process = subprocess.Popen(plan["argv"], cwd=plan["project"], stdout=output,
                                           stderr=subprocess.STDOUT, start_new_session=True)
                code = process.wait(timeout=plan["execution"]["timeout_seconds"])
                status = "command_succeeded" if code == 0 else "command_failed"
            except subprocess.TimeoutExpired:
                status = "timed_out"
            except KeyboardInterrupt:
                status = "interrupted"
            except OSError as error:
                output.write((type(error).__name__ + ": " + str(error)).encode())
            finally:
                if process is not None:
                    # Also stop children left behind by a completed launcher.
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait()
        after = self.protected()
        if after != plan["rules_sha256"]:
            status = "safety_violation"
        record = {"schema_version": "1.0.0", "id": run_id, "task": plan["task"],
                  "models": plan["models"],
                  "task_sha256": plan["task_sha256"], "task_snapshot": plan["task_snapshot"],
                  "started_at": started, "finished_at": now(), "status": status, "exit_code": code,
                  "environment": plan["environment"], "source": plan["source"], "n2s_revision": plan["n2s_revision"],
                  "rules_before": plan["rules_sha256"], "rules_after": after, "plan_sha256": approval,
                  "raw_log_sha256": file_hash(log), "summary": "Process result only; task acceptance and generality are not established.",
                  "evidence": [], "generalization": "pending_validation"}
        path = self.save_run(record)
        return {"run": str(path), "status": status, "raw_log": str(log), "review_required": True}

    def save_run(self, record):
        self.validate_data("run", record)
        return self.write(f"cases/work-items/{record['task'].split('/')[0]}/runs/{record['id']}/run.json", record)

    def check_assets(self, task, project):
        assets = {}
        for asset in task["protocol"]["assets"]:
            path = Path(asset["name"])
            if not path.is_absolute():
                path = project / path
            actual = file_hash(path)
            if actual != asset["sha256"]:
                raise ExperimentError("Asset checksum mismatch: " + asset["name"])
            assets[asset["name"]] = actual
        return assets

    def reviewed_text(self, evidence, confirmed):
        if not confirmed:
            raise ExperimentError("Review and redact the evidence, then pass --confirm-sanitized")
        if Path(evidence).stat().st_size > 1024 * 1024:
            raise ExperimentError("Reviewed evidence must be UTF-8 text no larger than 1 MiB")
        content = Path(evidence).read_bytes()
        check_text(content.decode("utf-8"))
        return content

    def attach(self, run_path, evidence, summary, confirmed):
        path, record = self.checked_run(run_path)
        content = self.reviewed_text(evidence, confirmed)
        parent_hash = digest(record)
        record["id"] = "report-" + uuid.uuid4().hex
        record["parent_run_sha256"] = parent_hash
        record["summary"] = summary
        record["evidence"] = [{"path": "evidence.txt", "sha256": hashlib.sha256(content).hexdigest()}]
        result = self.save_run(record)
        with result.with_name("evidence.txt").open("xb") as stream:
            stream.write(content)
        return {"run": str(result), "parent": str(path), "review_required": True}

    def record(self, key, project, outcome, summary, evidence, confirmed, python=sys.executable):
        task = self.task(key)
        content = self.reviewed_text(evidence, confirmed)
        check_text(summary)
        run_id = "record-" + uuid.uuid4().hex
        protected = self.protected()
        record = {"schema_version": "1.0.0", "id": run_id, "task": key, "task_sha256": digest(task),
                  "models": self.case_models(task["case_id"]),
                  "task_snapshot": task, "started_at": now(), "finished_at": now(), "status": outcome,
                  "exit_code": None, "environment": self.probe(python), "source": self.source(project),
                  "n2s_revision": git(self.root, "rev-parse", "HEAD"), "rules_before": protected,
                  "rules_after": protected, "plan_sha256": None, "raw_log_sha256": None,
                  "summary": summary, "evidence": [{"path": "evidence.txt", "sha256": hashlib.sha256(content).hexdigest()}],
                  "generalization": "pending_validation"}
        path = self.save_run(record)
        with path.with_name("evidence.txt").open("xb") as stream:
            stream.write(content)
        return {"run": str(path), "status": outcome, "review_required": True}

    def checked_run(self, run_path):
        path = Path(run_path).resolve()
        if not path.is_relative_to(self.path("cases/work-items")) or path.name != "run.json":
            raise ExperimentError("Expected a case run.json")
        self.path(path.relative_to(self.root))
        run = read_json(path)
        self.validate_data("run", run)
        self.validate_data("task", run["task_snapshot"])
        if digest(run["task_snapshot"]) != run["task_sha256"]:
            raise ExperimentError("Run task snapshot hash mismatch")
        snapshot = run["task_snapshot"]
        if run["task"] != snapshot["case_id"] + "/" + snapshot["id"]:
            raise ExperimentError("Run task identity mismatch")
        if path.parent.name != run["id"] or path.parents[2].name != run["task"].split("/")[0]:
            raise ExperimentError("Run path identity mismatch")
        for item in run["evidence"]:
            evidence = self.path(path.parent.relative_to(self.root) / item["path"])
            if evidence.parent != path.parent or file_hash(evidence) != item["sha256"]:
                raise ExperimentError("Evidence path or checksum mismatch")
            check_text(evidence.read_text(encoding="utf-8"))
        if "parent_run_sha256" in run:
            parents = [read_json(p) for p in self.runs(snapshot["case_id"]) if p != path]
            parent = next((p for p in parents if digest(p) == run["parent_run_sha256"]), None)
            if parent is None:
                raise ExperimentError("Missing original run for attached report")
            for key in run.keys() - {"id", "parent_run_sha256", "summary", "evidence"}:
                if run[key] != parent.get(key):
                    raise ExperimentError("Attached report changed original execution provenance")
        return path, run

    def review(self, run_path, reviewer, conclusion, summary):
        path, run = self.checked_run(run_path)
        if conclusion == "meets_task_acceptance":
            self.check_acceptance(run)
        review = {"schema_version": "1.0.0", "run_sha256": digest(run), "reviewer": reviewer,
                  "reviewed_at": now(), "conclusion": conclusion, "summary": summary,
                  "generalization": "pending_validation"}
        self.validate_data("review", review)
        result = self.write(path.with_name("review.json").relative_to(self.root), review)
        return {"review": str(result), "generalization": "pending_validation"}

    def check_acceptance(self, run):
        if run["status"] not in ("command_succeeded", "reported_pass") or run["rules_before"] != run["rules_after"]:
            raise ExperimentError("A failed or unsafe run cannot satisfy acceptance")
        if not run["evidence"]:
            raise ExperimentError("Attach a sanitized measurement report before accepting")
        if "pending:" in encoded(run["task_snapshot"]["protocol"]).decode().lower():
            raise ExperimentError("Define the task protocol before accepting evidence")

    def validate(self, case_id=None):
        reuse_path = self.path("evaluations/evidence-reuse.json")
        if reuse_path.exists():
            reuse = read_json(reuse_path)
            self.validate_data("reuse", reuse)
            for assessment in reuse["assessments"]:
                for key in assessment["next_tasks"]:
                    self.task(key)
                for reference in assessment["references"]:
                    if reference.startswith("upstream://"):
                        if not re.match(r"upstream://[a-z0-9-]+@[0-9a-f]{40}/.+", reference):
                            raise ExperimentError("External evidence must pin a full revision")
                    elif not self.path(reference).is_file():
                        raise ExperimentError("Missing evidence reference: " + reference)
        cases = [self.path(f"cases/work-items/{identifier(case_id)}")] if case_id else sorted(self.path("cases/work-items").glob("*"))
        count = 0
        graph = {}
        for directory in cases:
            if not directory.is_dir():
                continue
            issue = read_json(self.path(directory.relative_to(self.root) / "issue.json"))
            self.validate_data("issue", issue)
            if issue["id"] != directory.name:
                raise ExperimentError("Case ID mismatch")
            for path in directory.glob("tasks/*.json"):
                key = directory.name + "/" + path.stem
                task = self.task(key)
                graph[key] = task["depends_on"]
                for dep in task["depends_on"]:
                    self.task(dep)
            for path in self.runs(directory.name):
                path, run = self.checked_run(path)
                review_path = path.with_name("review.json")
                if review_path.exists():
                    review = read_json(review_path)
                    self.validate_data("review", review)
                    if review["run_sha256"] != digest(run):
                        raise ExperimentError("Review refers to a changed run")
                    if review["conclusion"] == "meets_task_acceptance":
                        self.check_acceptance(run)
                count += 1
        def visit(key, ancestors):
            if key in ancestors:
                raise ExperimentError("Dependency cycle: " + key)
            for dep in graph.get(key, self.task(key)["depends_on"]):
                visit(dep, ancestors | {key})
        for key in graph:
            visit(key, set())
        return {"status": "valid", "tasks": len(graph), "runs": count}

    def publish_check(self, case_id):
        self.validate(case_id)
        prefix = f"cases/work-items/{identifier(case_id)}/"
        staged = list(filter(None, git(self.root, "diff", "--cached", "--no-renames", "--name-only", "-z").split("\0")))
        if not staged or any(not name.startswith(prefix) for name in staged):
            raise ExperimentError("Stage only this case directory; unrelated or protected staged paths are forbidden")
        if git(self.root, "diff", "--name-only", "--", prefix):
            raise ExperimentError("Case has unstaged changes; reviewed files must equal the index")
        if git(self.root, "diff", "--cached", "--diff-filter=D", "--name-only", "--", prefix):
            raise ExperimentError("Case publication must not delete existing records")
        for name in staged:
            relative = name[len(prefix):]
            allowed = (relative == "issue.json"
                       or re.fullmatch(r"tasks/[a-z0-9-]+\.json", relative)
                       or re.fullmatch(r"runs/[a-z0-9-]+/(run\.json|review\.json|evidence\.txt)", relative)
                       or re.fullmatch(r"[a-zA-Z0-9_-]+\.md", relative))
            if not allowed:
                raise ExperimentError("Only case metadata, Markdown notes and reviewed run artifacts may be published")
            if "/runs/" in name:
                result = subprocess.run(["git", "cat-file", "-e", "HEAD:" + name], cwd=self.root, capture_output=True)
                if result.returncode == 0:
                    raise ExperimentError("Published run artifacts are immutable; append a new run instead")
            path = self.path(name)
            if path.stat().st_size > 1024 * 1024:
                raise ExperimentError("Large artifacts must stay outside Git")
            check_text(path.read_text(encoding="utf-8"))
        return {"status": "ready_for_user_review", "paths": staged,
                "staged_diff_sha256": hashlib.sha256(git(self.root, "diff", "--cached", "--binary").encode()).hexdigest(),
                "note": "No commit or push performed. Confirm destination, content and licensing with the user."}
