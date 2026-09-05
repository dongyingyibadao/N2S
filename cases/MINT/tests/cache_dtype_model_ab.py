#!/usr/bin/env python3
"""Materialize and run isolated MINT cache-dtype baseline/candidate variants."""

from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import difflib
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import traceback

import torch
import torch.nn.functional as F


SEED = 42
ACCEPTANCE = "record_only_no_unified_threshold"
DEFAULT_WARMUP = 1
DEFAULT_REPEATS = 5


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def exception_payload(exc: BaseException) -> dict[str, str]:
    return {
        "type": type(exc).__name__,
        "message": str(exc),
        "traceback_tail": "\n".join(traceback.format_exc().splitlines()[-12:]),
    }


def _assigned_name(node: ast.Assign, name: str) -> bool:
    return len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name


def _attribute_chain(node: ast.expr) -> list[str]:
    values = []
    while isinstance(node, ast.Attribute):
        values.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        values.append(node.id)
    return list(reversed(values))


def _is_projection_dtype(node: ast.expr) -> bool:
    return _attribute_chain(node)[-3:] == ["q_proj", "weight", "dtype"]


def _is_prefix_cast(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "to"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "prefix_embs"
        and any(
            keyword.arg == "dtype"
            and isinstance(keyword.value, ast.Name)
            and keyword.value.id == "prefix_dtype"
            for keyword in node.keywords
        )
    )


def build_cache_dtype_baseline_source(candidate_source: str) -> str:
    module = ast.parse(candidate_source)
    functions = [
        node
        for node in ast.walk(module)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "sample_actions"
    ]
    if len(functions) != 1:
        raise RuntimeError(f"expected exactly one sample_actions function, found {len(functions)}")
    dtype_nodes = []
    cast_nodes = []
    for node in functions[0].body:
        if not isinstance(node, ast.Assign):
            continue
        if _assigned_name(node, "prefix_dtype") and _is_projection_dtype(node.value):
            dtype_nodes.append(node)
        if _assigned_name(node, "prefix_embs") and _is_prefix_cast(node.value):
            cast_nodes.append(node)
    if len(dtype_nodes) != 1 or len(cast_nodes) != 1:
        raise RuntimeError(
            "expected exactly one inference prefix dtype lookup and cast; "
            f"found {len(dtype_nodes)} lookup(s) and {len(cast_nodes)} cast(s)"
        )
    removed_lines = set()
    for node in (*dtype_nodes, *cast_nodes):
        removed_lines.update(range(node.lineno, node.end_lineno + 1))
    baseline = "".join(
        line
        for line_number, line in enumerate(candidate_source.splitlines(keepends=True), start=1)
        if line_number not in removed_lines
    )
    ast.parse(baseline)
    if baseline == candidate_source:
        raise RuntimeError("baseline materialization did not change source")
    return baseline


def _torch_compile_call_count(node: ast.AST) -> int:
    return sum(
        1
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and isinstance(child.func.value, ast.Name)
        and child.func.value.id == "torch"
        and child.func.attr == "compile"
    )


def build_compile_baseline_source(candidate_source: str) -> str:
    module = ast.parse(candidate_source)
    matches = []
    for node in ast.walk(module):
        if not isinstance(node, ast.If) or _torch_compile_call_count(ast.Module(body=node.body)) < 1:
            continue
        test = ast.unparse(node.test)
        if (
            "config.compile_model" in test
            and "config.device" in test
            and len(node.orelse) == 1
            and isinstance(node.orelse[0], ast.If)
            and ast.unparse(node.orelse[0].test) == "config.compile_model"
        ):
            matches.append(node)
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one guarded compile block, found {len(matches)}")
    node = matches[0]
    if node.lineno != node.test.lineno or node.test.end_lineno != node.lineno:
        raise RuntimeError("compile guard is multiline; refusing line-oriented baseline materialization")
    lines = candidate_source.splitlines(keepends=True)
    indent = lines[node.lineno - 1][: len(lines[node.lineno - 1]) - len(lines[node.lineno - 1].lstrip())]
    lines[node.lineno - 1] = f"{indent}if config.compile_model:\n"
    nested_else = node.orelse[0]
    for line_number in range(nested_else.lineno, nested_else.end_lineno + 1):
        lines[line_number - 1] = ""
    baseline = "".join(lines)
    ast.parse(baseline)
    return baseline


def build_sinusoidal_baseline_source(candidate_source: str) -> str:
    module = ast.parse(candidate_source)
    functions = [
        node for node in ast.walk(module) if isinstance(node, ast.FunctionDef) and node.name == "get_safe_dtype"
    ]
    if len(functions) != 1:
        raise RuntimeError(f"expected exactly one get_safe_dtype function, found {len(functions)}")
    matches = []
    for node in functions[0].body:
        if not isinstance(node, ast.If):
            continue
        rendered = ast.unparse(node.test)
        if (
            "device_type in {'mps', 'npu'}" in rendered
            and "target_dtype == torch.float64" in rendered
            and any(
                isinstance(child, ast.Return) and ast.unparse(child.value) == "torch.float32"
                for child in node.body
            )
        ):
            matches.append(node)
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one NPU sinusoidal dtype guard, found {len(matches)}")
    node = matches[0]
    if node.lineno != node.test.lineno or node.test.end_lineno != node.lineno:
        raise RuntimeError("sinusoidal guard is multiline; refusing line-oriented baseline materialization")
    lines = candidate_source.splitlines(keepends=True)
    indent = lines[node.lineno - 1][: len(lines[node.lineno - 1]) - len(lines[node.lineno - 1].lstrip())]
    lines[node.lineno - 1] = (
        f'{indent}if device_type == "mps" and target_dtype == torch.float64:\n'
    )
    baseline = "".join(lines)
    ast.parse(baseline)
    return baseline


def build_baseline_source(candidate_source: str, rule: str = "cache-dtype") -> str:
    builders = {
        "cache-dtype": build_cache_dtype_baseline_source,
        "compile": build_compile_baseline_source,
        "sinusoidal-fp64": build_sinusoidal_baseline_source,
    }
    return builders[rule](candidate_source)


def _call_count(source: str, function_name: str) -> int:
    module = ast.parse(source)
    return sum(
        1
        for node in ast.walk(module)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == function_name
    )


def materialize_variants(source_root: Path, destination: Path, rule: str = "cache-dtype") -> dict:
    package_source = source_root / "lerobot_policy_mint"
    modeling_source = package_source / "modeling_mint.py"
    if not modeling_source.is_file():
        raise FileNotFoundError(f"MINT modeling source not found: {modeling_source}")
    candidate_source = modeling_source.read_text(encoding="utf-8")
    baseline_source = build_baseline_source(candidate_source, rule)

    roots = {}
    for variant in ("baseline", "candidate"):
        variant_root = destination / variant / "src"
        shutil.copytree(source_root, variant_root)
        roots[variant] = variant_root
    (roots["baseline"] / "lerobot_policy_mint" / "modeling_mint.py").write_text(
        baseline_source, encoding="utf-8"
    )

    diff = "".join(
        difflib.unified_diff(
            baseline_source.splitlines(keepends=True),
            candidate_source.splitlines(keepends=True),
            fromfile="baseline/modeling_mint.py",
            tofile="candidate/modeling_mint.py",
        )
    )
    return {
        "roots": roots,
        "candidate_sha256": sha256_bytes(candidate_source.encode()),
        "baseline_sha256": sha256_bytes(baseline_source.encode()),
        "diff_sha256": sha256_bytes(diff.encode()),
        "diff": diff,
        "matched_helper_call_count": (
            _call_count(candidate_source, "create_sinusoidal_pos_embedding")
            if rule == "sinusoidal-fp64"
            else None
        ),
    }


def backend_api(name: str, index: int):
    module_version = None
    if name == "npu":
        import torch_npu

        module_version = torch_npu.__version__
        api = torch.npu
    else:
        api = torch.cuda
    if not api.is_available():
        raise RuntimeError(f"torch.{name}.is_available() is false")
    api.set_device(index)
    return api, torch.device(f"{name}:{index}"), module_version


def numerical_metrics(reference: torch.Tensor, candidate: torch.Tensor) -> dict[str, float]:
    ref = reference.detach().cpu().double().reshape(-1)
    got = candidate.detach().cpu().double().reshape(-1)
    delta = got - ref
    return {
        "max_abs_error": delta.abs().max().item(),
        "max_relative_error": (delta.abs() / ref.abs().clamp_min(1e-12)).max().item(),
        "rmse": delta.square().mean().sqrt().item(),
        "cosine_similarity": F.cosine_similarity(ref[None, :], got[None, :]).item(),
    }


def tensor_record(value: torch.Tensor) -> dict:
    cpu = value.detach().cpu().contiguous()
    return {
        "shape": list(cpu.shape),
        "dtype": str(cpu.dtype),
        "finite": bool(torch.isfinite(cpu).all().item()),
        "content_sha256": sha256_bytes(cpu.numpy().tobytes()),
    }


def percentile95(samples: list[float]) -> float:
    return sorted(samples)[math.ceil(0.95 * len(samples)) - 1]


def checkpoint_record(checkpoint: Path | None) -> dict | None:
    if checkpoint is None:
        return None
    files = []
    for name in ("config.json", "model.safetensors"):
        path = checkpoint / name
        if path.is_file():
            files.append({"path": name, "size_bytes": path.stat().st_size, "sha256": sha256_file(path)})
    if not any(item["path"] == "model.safetensors" for item in files):
        raise FileNotFoundError(f"checkpoint has no model.safetensors: {checkpoint}")
    return {"path": str(checkpoint.resolve()), "files": files}


def _load_model(checkpoint: Path | None, backend: str, mode: str, rule: str):
    from lerobot_policy_mint.configuration_mint import MINTConfig
    from lerobot_policy_mint.modeling_mint import MINTPolicy, MINTPytorch

    if checkpoint is None:
        config = MINTConfig(
            device=backend,
            dtype="bfloat16",
            compile_model=rule == "compile",
            gradient_checkpointing=mode == "training",
        )
        return MINTPytorch(config), config, "random-weight structure-only control"

    from lerobot.configs.policies import PreTrainedConfig

    config = PreTrainedConfig.from_pretrained(
        checkpoint,
        cli_overrides=[
            f"--device={backend}",
            f"--compile_model={str(rule == 'compile').lower()}",
            f"--gradient_checkpointing={str(mode == 'training').lower()}",
        ],
    )
    if config.type != "mint":
        raise ValueError(f"expected MINT checkpoint, got {config.type!r}")
    policy = MINTPolicy.from_pretrained(checkpoint, config=config)
    return policy.model, config, f"pretrained checkpoint: {checkpoint.resolve()}"


def _to_device_inputs(payload: dict, device: torch.device) -> dict:
    return {
        "images": [value.to(device) for value in payload["images"]],
        "image_masks": [value.to(device) for value in payload["image_masks"]],
        "tokens": payload["tokens"].to(device),
        "token_masks": payload["token_masks"].to(device),
        "actions": payload["actions"].to(device),
    }


def _run_inference(model, inputs: dict, api, warmup: int, repeats: int) -> tuple[dict, dict]:
    captured_logits: list[torch.Tensor] = []
    original_sampler = model.sample_with_top_k_top_p_

    def capture_sampler(logits, *args, **kwargs):
        captured_logits.append(logits.detach().float().cpu())
        return original_sampler(logits, *args, **kwargs)

    model.sample_with_top_k_top_p_ = capture_sampler
    model.eval()
    with torch.inference_mode():
        for _ in range(warmup):
            model.sample_actions(
                inputs["images"], inputs["image_masks"], inputs["tokens"], inputs["token_masks"], sample_top_k=1
            )
            api.synchronize()
        captured_logits.clear()
        samples = []
        for _ in range(repeats):
            captured_logits.clear()
            started = time.perf_counter()
            action, intention = model.sample_actions(
                inputs["images"], inputs["image_masks"], inputs["tokens"], inputs["token_masks"], sample_top_k=1
            )
            api.synchronize()
            samples.append(time.perf_counter() - started)
    tensors = {
        "action": action.detach().float().cpu(),
        "intention": intention.detach().float().cpu(),
        "logits": captured_logits,
    }
    metrics = {
        "action": tensor_record(tensors["action"]),
        "intention": tensor_record(tensors["intention"]),
        "logits": [tensor_record(value) for value in tensors["logits"]],
    }
    return {"samples": samples, "outputs": metrics}, tensors


def _run_training(model, config, inputs: dict, api) -> tuple[dict, dict]:
    model.train()
    model.gradient_checkpointing_enable()
    optimizer = torch.optim.AdamW(
        (parameter for parameter in model.parameters() if parameter.requires_grad),
        lr=2e-4,
        betas=(0.9, 0.95),
        eps=1e-8,
        weight_decay=0.01,
    )
    started = time.perf_counter()
    loss = model(
        inputs["images"],
        inputs["image_masks"],
        inputs["tokens"],
        inputs["token_masks"],
        inputs["actions"][..., : config.max_action_dim],
    ).mean()
    loss.backward()
    gradient = model.vq_code_out_proj.weight.grad.detach().float().cpu()
    optimizer.step()
    optimizer.zero_grad(set_to_none=True)
    api.synchronize()
    samples = [time.perf_counter() - started]
    tensors = {"loss": loss.detach().float().cpu().reshape(1), "gradient": gradient}
    metrics = {
        "loss": loss.item(),
        "finite_loss": bool(torch.isfinite(loss).item()),
        "selected_gradient": tensor_record(gradient),
        "optimizer_updates": 1,
    }
    return {"samples": samples, "outputs": metrics}, tensors


def worker_run(args: argparse.Namespace) -> dict:
    result = {
        "variant": args.variant,
        "status": "failed",
        "backend": args.backend,
        "rule": args.rule,
        "mode": args.mode,
        "seed": SEED,
        "source_sha256": sha256_file(args.source_root / "lerobot_policy_mint" / "modeling_mint.py"),
        "samples": [],
        "metrics": {},
        "memory": {},
        "exception": None,
    }
    api = None
    run_started = None
    try:
        api, device, module_version = backend_api(args.backend, args.device_index)
        torch.manual_seed(SEED)
        payload = torch.load(args.input_tensor, map_location="cpu", weights_only=True)
        build_started = time.perf_counter()
        model, config, scope = _load_model(args.checkpoint, args.backend, args.mode, args.rule)
        import lerobot_policy_mint.modeling_mint as imported_modeling

        imported_path = Path(imported_modeling.__file__).resolve()
        expected_package = (args.source_root / "lerobot_policy_mint").resolve()
        if not imported_path.is_relative_to(expected_package):
            raise RuntimeError(
                f"model imported outside materialized variant: {imported_path} not below {expected_package}"
            )
        model = model.to(device)
        api.synchronize()
        build_seconds = time.perf_counter() - build_started
        result.update(
            scope=scope,
            metrics={"build_seconds": build_seconds},
            environment={
                "device": api.get_device_name(args.device_index),
                "device_index": args.device_index,
                "torch": torch.__version__,
                f"torch_{args.backend}": module_version,
                "python": platform.python_version(),
                "platform": platform.platform(),
            },
            imported_source={
                "path": str(imported_path),
                "sha256": sha256_file(imported_path),
            },
        )
        sinusoidal_probe = None
        if args.rule == "sinusoidal-fp64":
            probe_time = torch.tensor(
                [0.0, 0.001, 0.01, 0.125, 0.5, 0.999, 1.0],
                device=device,
                dtype=torch.float32,
            )
            sinusoidal_probe = imported_modeling.create_sinusoidal_pos_embedding(
                probe_time,
                256,
                0.004,
                4.0,
                device=device,
            )
            api.synchronize()
            result["metrics"]["sinusoidal_probe"] = tensor_record(sinusoidal_probe)
        inputs = _to_device_inputs(payload, device)
        api.synchronize()
        starting_allocated = int(api.memory_allocated(args.device_index))
        api.reset_peak_memory_stats(args.device_index)
        result["memory"] = {"starting_allocated_bytes": starting_allocated}
        run_started = time.perf_counter()
        if args.mode == "inference":
            run_result, tensors = _run_inference(model, inputs, api, args.warmup, args.repeats)
        else:
            run_result, tensors = _run_training(model, config, inputs, api)
        if sinusoidal_probe is not None:
            tensors["sinusoidal_probe"] = sinusoidal_probe.detach().cpu()
        peak_allocated = int(api.max_memory_allocated(args.device_index))
        torch.save(tensors, args.output_tensor)
        samples = run_result["samples"]
        result.update(
            status="passed",
            samples=samples,
            metrics={
                **result["metrics"],
                "build_seconds": build_seconds,
                "median_seconds": statistics.median(samples),
                "p95_seconds": percentile95(samples),
                **run_result["outputs"],
            },
            memory={
                "starting_allocated_bytes": starting_allocated,
                "peak_allocated_bytes": peak_allocated,
                "peak_increment_bytes": max(0, peak_allocated - starting_allocated),
            },
        )
    except Exception as exc:
        result["exception"] = exception_payload(exc)
        if run_started is not None:
            result["metrics"]["time_to_exception_seconds"] = time.perf_counter() - run_started
        if api is not None and result["memory"].get("starting_allocated_bytes") is not None:
            try:
                api.synchronize()
                peak_allocated = int(api.max_memory_allocated(args.device_index))
                starting_allocated = result["memory"]["starting_allocated_bytes"]
                result["memory"].update(
                    peak_allocated_bytes=peak_allocated,
                    peak_increment_bytes=max(0, peak_allocated - starting_allocated),
                )
            except Exception as memory_exc:
                result["memory"]["collection_error"] = str(memory_exc)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def create_input(path: Path, batch_size: int, image_count: int, token_length: int) -> dict:
    generator = torch.Generator(device="cpu").manual_seed(SEED)
    payload = {
        "images": [
            torch.randn(batch_size, 3, 224, 224, generator=generator, dtype=torch.float32)
            for _ in range(image_count)
        ],
        "image_masks": [torch.ones(batch_size, dtype=torch.bool) for _ in range(image_count)],
        "tokens": torch.zeros(batch_size, token_length, dtype=torch.long),
        "token_masks": torch.ones(batch_size, token_length, dtype=torch.bool),
        "actions": torch.randn(batch_size, 16, 7, generator=generator, dtype=torch.float32).clamp(-1, 1),
    }
    torch.save(payload, path)
    return {
        "sha256": sha256_file(path),
        "batch_size": batch_size,
        "image_count": image_count,
        "image_shape": [batch_size, 3, 224, 224],
        "image_dtype": "torch.float32",
        "token_shape": [batch_size, token_length],
        "action_shape": [batch_size, 16, 7],
    }


def topk_metrics(reference: torch.Tensor, candidate: torch.Tensor, k: int) -> dict[str, float]:
    actual_k = min(k, reference.shape[-1])
    ref_indices = reference.topk(actual_k, dim=-1).indices
    got_indices = candidate.topk(actual_k, dim=-1).indices
    exact_rows = (ref_indices.sort(dim=-1).values == got_indices.sort(dim=-1).values).all(dim=-1)
    overlap = (ref_indices.unsqueeze(-1) == got_indices.unsqueeze(-2)).any(dim=-1).float().mean()
    return {
        "k": actual_k,
        "exact_set_agreement_fraction": exact_rows.float().mean().item(),
        "mean_reference_member_overlap_fraction": overlap.item(),
    }


def compare_outputs(baseline_path: Path, candidate_path: Path, mode: str) -> dict:
    baseline = torch.load(baseline_path, map_location="cpu", weights_only=True)
    candidate = torch.load(candidate_path, map_location="cpu", weights_only=True)
    probe = {}
    if "sinusoidal_probe" in baseline or "sinusoidal_probe" in candidate:
        if "sinusoidal_probe" not in baseline or "sinusoidal_probe" not in candidate:
            raise RuntimeError("only one variant produced the sinusoidal probe")
        probe["sinusoidal_probe"] = numerical_metrics(
            baseline["sinusoidal_probe"], candidate["sinusoidal_probe"]
        )
    if mode == "training":
        return {
            "loss": numerical_metrics(baseline["loss"], candidate["loss"]),
            "selected_gradient": numerical_metrics(baseline["gradient"], candidate["gradient"]),
            **probe,
        }
    if len(baseline["logits"]) != len(candidate["logits"]):
        raise RuntimeError("baseline and candidate captured different logit scale counts")
    logits = []
    for scale, (reference, got) in enumerate(zip(baseline["logits"], candidate["logits"], strict=True)):
        logits.append(
            {
                "scale": scale,
                "numerical": numerical_metrics(reference, got),
                "top1": topk_metrics(reference, got, 1),
                "top5": topk_metrics(reference, got, 5),
            }
        )
    return {
        "action": numerical_metrics(baseline["action"], candidate["action"]),
        "intention": numerical_metrics(baseline["intention"], candidate["intention"]),
        "logits": logits,
        **probe,
    }


def base_test(test_id: str, input_spec: dict, checkpoint: dict | None, classification: str = "numerical_precision") -> dict:
    return {
        "id": test_id,
        "classification": classification,
        "status": "failed",
        "evidence_status": "static_analysis",
        "seed": SEED,
        "input": input_spec,
        "checkpoint": checkpoint,
        "samples": [],
        "metrics": {},
        "memory": {},
        "exception": None,
        "acceptance": ACCEPTANCE,
    }


def run_variant(
    args: argparse.Namespace,
    variant: str,
    source_root: Path,
    temporary: Path,
) -> tuple[dict, Path, dict]:
    output_json = temporary / f"{variant}.json"
    output_tensor = temporary / f"{variant}.pt"
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "_worker",
        "--variant",
        variant,
        "--rule",
        args.rule,
        "--backend",
        args.backend,
        "--device-index",
        str(args.device_index),
        "--mode",
        args.mode,
        "--source-root",
        str(source_root),
        "--input-tensor",
        str(temporary / "input.pt"),
        "--output-json",
        str(output_json),
        "--output-tensor",
        str(output_tensor),
        "--warmup",
        str(args.warmup),
        "--repeats",
        str(args.repeats),
    ]
    if args.checkpoint is not None:
        command.extend(["--checkpoint", str(args.checkpoint.resolve())])
    env = os.environ.copy()
    env["PYTHONPATH"] = str(source_root) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    completed = subprocess.run(
        command,
        env=env,
        text=True,
        capture_output=True,
        timeout=args.timeout,
        check=False,
    )
    process = {
        "returncode": completed.returncode,
        "stdout_tail": "\n".join(completed.stdout.splitlines()[-20:]),
        "stderr_tail": "\n".join(completed.stderr.splitlines()[-40:]),
    }
    if output_json.is_file():
        result = json.loads(output_json.read_text(encoding="utf-8"))
    else:
        result = {
            "variant": variant,
            "status": "failed",
            "samples": [],
            "metrics": {},
            "memory": {},
            "exception": {
                "type": "WorkerFailure",
                "message": "worker did not write its result",
                "traceback_tail": process["stderr_tail"],
            },
        }
    return result, output_tensor, process


def orchestrate(args: argparse.Namespace) -> dict:
    checkpoint = checkpoint_record(args.checkpoint)
    with tempfile.TemporaryDirectory(prefix=f"n2s-{args.rule}-ab-") as temporary_name:
        temporary = Path(temporary_name)
        variants = materialize_variants(args.source_root.resolve(), temporary / "variants", args.rule)
        input_spec = create_input(temporary / "input.pt", args.batch_size, args.images, args.token_length)
        input_spec.update(
            mode=args.mode,
            warmup=args.warmup if args.mode == "inference" else 0,
            repeats=args.repeats if args.mode == "inference" else 1,
            variant_order=args.variant_order,
        )
        results = {}
        tensors = {}
        processes = {}
        for variant in args.variant_order.split(","):
            result, tensor_path, process = run_variant(
                args, variant, variants["roots"][variant], temporary
            )
            results[variant] = result
            tensors[variant] = tensor_path
            processes[variant] = process

        test_prefix = {
            "cache-dtype": "cache_dtype",
            "compile": "compile_capability",
            "sinusoidal-fp64": "sinusoidal_fp64",
        }[args.rule]
        classification = "operator_implementation" if args.rule == "compile" else "numerical_precision"
        test_id = f"{test_prefix}_model_{args.mode}_ab"
        test = base_test(test_id, input_spec, checkpoint, classification)
        test["variants"] = results
        test["processes"] = processes
        test["source"] = {
            "candidate_root": str(args.source_root.resolve()),
            "candidate_modeling_sha256": variants["candidate_sha256"],
            "baseline_modeling_sha256": variants["baseline_sha256"],
            "baseline_to_candidate_diff_sha256": variants["diff_sha256"],
            "baseline_to_candidate_diff": variants["diff"],
            "matched_helper_call_count": variants["matched_helper_call_count"],
        }
        candidate_passed = results.get("candidate", {}).get("status") == "passed"
        baseline_passed = results.get("baseline", {}).get("status") == "passed"
        test["metrics"]["functional_outcome"] = (
            f"baseline_{'passed' if baseline_passed else 'failed'}_candidate_"
            f"{'passed' if candidate_passed else 'failed'}"
        )
        if baseline_passed and candidate_passed:
            test["metrics"]["candidate_vs_baseline"] = compare_outputs(
                tensors["baseline"], tensors["candidate"], args.mode
            )
            baseline_median = results["baseline"]["metrics"]["median_seconds"]
            candidate_median = results["candidate"]["metrics"]["median_seconds"]
            test["metrics"]["candidate_median_ratio"] = candidate_median / baseline_median
        if candidate_passed:
            test["samples"] = results["candidate"]["samples"]
            test["baseline_samples"] = results["baseline"].get("samples", [])
            test["memory"] = {
                "baseline": results["baseline"].get("memory", {}),
                "candidate": results["candidate"].get("memory", {}),
            }
            if baseline_passed:
                test["memory"]["candidate_minus_baseline_peak_allocated_bytes"] = (
                    results["candidate"]["memory"]["peak_allocated_bytes"]
                    - results["baseline"]["memory"]["peak_allocated_bytes"]
                )
            test["status"] = "passed"
            test["evidence_status"] = f"{args.backend}_passed"
        else:
            test["exception"] = results.get("candidate", {}).get("exception")
            test["evidence_status"] = f"{args.backend}_failed"

        environment = results.get("candidate", {}).get("environment") or results.get("baseline", {}).get(
            "environment"
        ) or {"torch": torch.__version__, "platform": platform.platform()}
        return {
            "schema_version": "1.0.0",
            "case": "MINT",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "promotion_status": "exploratory",
            "backend": args.backend,
            "environment": environment,
            "tests": [test],
        }


def worker_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--variant", choices=("baseline", "candidate"), required=True)
    parser.add_argument("--rule", choices=("cache-dtype", "compile", "sinusoidal-fp64"), required=True)
    parser.add_argument("--backend", choices=("npu", "cuda"), required=True)
    parser.add_argument("--device-index", type=int, required=True)
    parser.add_argument("--mode", choices=("inference", "training"), required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--input-tensor", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-tensor", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--warmup", type=int, required=True)
    parser.add_argument("--repeats", type=int, required=True)
    return parser


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "_worker":
        args = worker_parser().parse_args(sys.argv[2:])
        worker_run(args)
        return 0

    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("npu", "cuda"), required=True)
    parser.add_argument("--rule", choices=("cache-dtype", "compile", "sinusoidal-fp64"), default="cache-dtype")
    parser.add_argument("--device-index", type=int, default=0)
    parser.add_argument("--mode", choices=("inference", "training"), default="inference")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--images", type=int, default=2)
    parser.add_argument("--token-length", type=int, default=32)
    parser.add_argument("--warmup", type=int, default=DEFAULT_WARMUP)
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    parser.add_argument("--variant-order", choices=("baseline,candidate", "candidate,baseline"), default="baseline,candidate")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if (
        args.device_index < 0
        or args.batch_size < 1
        or args.images < 1
        or args.token_length < 1
        or args.warmup < 0
        or args.repeats < 1
        or args.timeout < 1
    ):
        parser.error("indices/warmup must be non-negative and sizes/repeats/timeout must be positive")
    if not args.source_root.is_dir():
        parser.error(f"source root is not a directory: {args.source_root}")
    if args.checkpoint is not None and not args.checkpoint.is_dir():
        parser.error(f"checkpoint is not a directory: {args.checkpoint}")
    if args.mode == "training":
        args.warmup = 0
        args.repeats = 1

    try:
        result = orchestrate(args)
    except Exception as exc:
        test = base_test(
            f"{args.rule.replace('-', '_')}_model_{args.mode}_ab",
            {"mode": args.mode, "variant_order": args.variant_order},
            None,
            "operator_implementation" if args.rule == "compile" else "numerical_precision",
        )
        test["exception"] = exception_payload(exc)
        test["evidence_status"] = f"{args.backend}_failed"
        result = {
            "schema_version": "1.0.0",
            "case": "MINT",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "promotion_status": "exploratory",
            "backend": args.backend,
            "environment": {"torch": torch.__version__, "platform": platform.platform()},
            "tests": [test],
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["tests"][0]["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
