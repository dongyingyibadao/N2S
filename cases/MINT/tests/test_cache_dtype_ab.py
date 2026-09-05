import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from jsonschema import Draft202012Validator
import torch


CASE_ROOT = Path(__file__).resolve().parents[1]
N2S_ROOT = CASE_ROOT.parents[1]
SOURCE_ROOT = CASE_ROOT / "sources/ascend-v062/lerobot_policy_mint/src"


def load_script(name: str):
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(f"test_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


operator_ab = load_script("cache_dtype_ab.py")
model_ab = load_script("cache_dtype_model_ab.py")
runtime_ab = load_script("runtime_rule_ab.py")


class CacheDtypeHarnessTests(unittest.TestCase):
    def test_baseline_materialization_removes_only_inference_cast(self):
        candidate_path = SOURCE_ROOT / "lerobot_policy_mint/modeling_mint.py"
        candidate = candidate_path.read_text(encoding="utf-8")
        baseline = model_ab.build_baseline_source(candidate)
        self.assertEqual(1, candidate.count("prefix_embs = prefix_embs.to(dtype=prefix_dtype)"))
        self.assertEqual(0, baseline.count("prefix_embs = prefix_embs.to(dtype=prefix_dtype)"))
        self.assertIn("suffix_embs = suffix_embs.to(dtype=torch.bfloat16)", baseline)
        self.assertIn("prefix_embs = prefix_embs.to(dtype=torch.bfloat16)", baseline)
        self.assertEqual(215, len(candidate) - len(baseline))

    def test_baseline_materialization_rejects_unknown_shape(self):
        source = """\
class Policy:
    def sample_actions(self):
        prefix_embs = self.embed_prefix()
        return prefix_embs
"""
        with self.assertRaisesRegex(RuntimeError, "expected exactly one"):
            model_ab.build_baseline_source(source)

    def test_materialized_variants_are_hash_pinned(self):
        with tempfile.TemporaryDirectory() as temporary_name:
            result = model_ab.materialize_variants(SOURCE_ROOT, Path(temporary_name))
            baseline = result["roots"]["baseline"] / "lerobot_policy_mint/modeling_mint.py"
            candidate = result["roots"]["candidate"] / "lerobot_policy_mint/modeling_mint.py"
            self.assertEqual(result["baseline_sha256"], model_ab.sha256_file(baseline))
            self.assertEqual(result["candidate_sha256"], model_ab.sha256_file(candidate))
            self.assertIn("+        prefix_embs = prefix_embs.to(dtype=prefix_dtype)", result["diff"])

    def test_compile_baseline_materialization_is_only_guard_rollback(self):
        candidate = (SOURCE_ROOT / "lerobot_policy_mint/modeling_mint.py").read_text(encoding="utf-8")
        baseline = model_ab.build_baseline_source(candidate, "compile")
        self.assertIn("if config.compile_model:\n", baseline)
        self.assertNotIn('not str(config.device).startswith("npu")', baseline)
        self.assertNotIn("torch.compile is disabled for MINT", baseline)
        self.assertEqual(candidate.count("torch.compile("), baseline.count("torch.compile("))

    def test_sinusoidal_baseline_and_unused_helper_are_recorded(self):
        candidate = (SOURCE_ROOT / "lerobot_policy_mint/modeling_mint.py").read_text(encoding="utf-8")
        baseline = model_ab.build_baseline_source(candidate, "sinusoidal-fp64")
        self.assertIn('device_type == "mps" and target_dtype == torch.float64', baseline)
        self.assertEqual(0, model_ab._call_count(candidate, "create_sinusoidal_pos_embedding"))

    def test_model_pair_metrics_include_numerical_and_topk(self):
        generator = torch.Generator().manual_seed(42)
        baseline = {
            "action": torch.randn(1, 16, 7, generator=generator),
            "intention": torch.randn(1, 32, generator=generator),
            "logits": [torch.randn(1, size, 16, generator=generator) for size in (1, 2, 4)],
        }
        candidate = {key: value if key != "logits" else list(value) for key, value in baseline.items()}
        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            torch.save(baseline, root / "baseline.pt")
            torch.save(candidate, root / "candidate.pt")
            metrics = model_ab.compare_outputs(root / "baseline.pt", root / "candidate.pt", "inference")
        self.assertEqual(0.0, metrics["action"]["max_abs_error"])
        self.assertEqual(3, len(metrics["logits"]))
        self.assertEqual(1.0, metrics["logits"][2]["top5"]["exact_set_agreement_fraction"])

    def test_unavailable_cuda_operator_result_matches_schema(self):
        if torch.cuda.is_available():
            self.skipTest("test expects a host without CUDA")
        result = operator_ab.run("cuda", 0, warmup=0, repeats=1)
        schema = json.loads((CASE_ROOT / "schemas/result.schema.json").read_text(encoding="utf-8"))
        errors = list(Draft202012Validator(schema).iter_errors(result))
        self.assertEqual([], [error.message for error in errors])
        self.assertEqual("pending_cuda", result["tests"][0]["status"])

    def test_runtime_harness_cpu_sinusoidal_reference_is_exact(self):
        time_values = torch.tensor([0.0, 0.125, 1.0], dtype=torch.float64)
        first = runtime_ab.sinusoidal(time_values, 32, 0.004, 4.0, torch.float64)
        second = runtime_ab.sinusoidal(time_values, 32, 0.004, 4.0, torch.float64)
        self.assertEqual((3, 32), tuple(first.shape))
        self.assertEqual(0.0, runtime_ab.numerical_metrics(first, second)["max_abs_error"])

    def test_unavailable_cuda_runtime_result_matches_schema(self):
        if torch.cuda.is_available():
            self.skipTest("test expects a host without CUDA")
        result = runtime_ab.run("cuda", 0, warmup=0, repeats=1)
        schema = json.loads((CASE_ROOT / "schemas/result.schema.json").read_text(encoding="utf-8"))
        errors = list(Draft202012Validator(schema).iter_errors(result))
        self.assertEqual([], [error.message for error in errors])
        self.assertEqual("pending_cuda", result["tests"][0]["status"])

    def test_cuda_capture_validator_accepts_block_only_set_and_rejects_checkpoint_data(self):
        cuda_root = CASE_ROOT / "cuda"
        result_ids = {
            "candidate_checks.json": [
                "sinusoidal_fp32_fallback",
                "eager_fixed_input",
                "compile_fixed_input",
                "sdpa_mixed_dtype_control",
                "sdpa_aligned_dtype",
            ],
            "cache_dtype_operator_ab.json": [
                "cache_dtype_functional_ab",
                "cache_dtype_cast_overhead_ab",
                "cache_dtype_already_aligned_control",
            ],
            "runtime_rule_ab.json": [
                "sinusoidal_fp64_functional_ab",
                "sinusoidal_fp64_performance_ab",
                "compile_capability_ab",
            ],
        }
        with tempfile.TemporaryDirectory() as temporary_name:
            root = Path(temporary_name)
            for name, test_ids in result_ids.items():
                tests = [
                    {
                        "id": test_id,
                        "classification": "numerical_precision",
                        "status": "passed",
                        "evidence_status": "cuda_passed",
                        "seed": 42,
                        "input": {},
                        "checkpoint": None,
                        "samples": [],
                        "metrics": {},
                        "memory": {},
                        "exception": None,
                        "acceptance": "record_only_no_unified_threshold",
                    }
                    for test_id in test_ids
                ]
                payload = {
                    "schema_version": "1.0.0",
                    "case": "MINT",
                    "generated_at": "2026-08-31T00:00:00+00:00",
                    "promotion_status": "exploratory",
                    "backend": "cuda",
                    "environment": {
                        "device": "Synthetic NVIDIA",
                        "torch": "2.9.0+cu128",
                        "cuda_runtime": "12.8",
                    },
                    "tests": tests,
                }
                (root / name).write_text(json.dumps(payload), encoding="utf-8")
                (root / name.removesuffix(".json")).with_suffix(".log").write_text("captured\n")
            for name in (
                "nvidia_smi.log",
                "pip_freeze.log",
                "preflight.json",
                "install.log",
                "harness_exit_code.txt",
                "bundle_verification.log",
            ):
                (root / name).write_text("captured\n")
            command = [
                sys.executable,
                str(cuda_root / "validate_results.py"),
                "--results",
                str(root),
                "--harness-exit-code",
                "0",
                "--output",
                str(root / "manifest.json"),
            ]
            subprocess.run(command, check=True, capture_output=True, text=True)
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            schema = json.loads((cuda_root / "cuda-validation.schema.json").read_text(encoding="utf-8"))
            self.assertEqual([], list(Draft202012Validator(schema).iter_errors(manifest)))
            self.assertEqual("operator_block_ab", manifest["scope"])
            self.assertFalse(manifest["model_execution"])
            self.assertFalse(manifest["model_parameters_loaded"])
            self.assertEqual(3, len(manifest["results"]))

            drifted = json.loads((root / "candidate_checks.json").read_text(encoding="utf-8"))
            drifted["tests"][0]["checkpoint"] = {"path": "/unexpected/model"}
            (root / "candidate_checks.json").write_text(json.dumps(drifted), encoding="utf-8")
            failed = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(0, failed.returncode)
            self.assertIn("must not record a checkpoint in block-only mode", failed.stderr)

    def test_cuda_bundle_excludes_model_code_and_checkpoint(self):
        build_script = (CASE_ROOT / "build_cuda_bundle.sh").read_text(encoding="utf-8")
        runner = (CASE_ROOT / "cuda/run_bundle.sh").read_text(encoding="utf-8")
        requirements = (CASE_ROOT / "cuda/requirements-cu128.txt").read_text(encoding="utf-8")
        self.assertNotIn("cache_dtype_model_ab.py", build_script)
        self.assertNotIn("checkpoint.json", build_script)
        self.assertNotIn("sources/ascend-v062", build_script)
        self.assertNotIn("N2S_RUN_MODEL", runner)
        self.assertNotIn("N2S_MINT_CHECKPOINT", runner)
        self.assertNotIn("lerobot", requirements.lower())
        self.assertNotIn("transformers", requirements.lower())
        self.assertFalse((CASE_ROOT / "cuda/checkpoint.json").exists())


if __name__ == "__main__":
    unittest.main()
