#!/usr/bin/env python

import argparse
import json
import os
from pathlib import Path

import torch
import torch_npu  # noqa: F401


def require_file(path: Path, minimum_bytes: int = 1) -> None:
    if not path.is_file() or path.stat().st_size < minimum_bytes:
        raise FileNotFoundError(f"Missing or incomplete file: {path}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--tokenizer", type=Path)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--require-weights", action="store_true")
    parser.add_argument("--require-complete-dataset", action="store_true")
    args = parser.parse_args()

    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.policies import get_policy_class
    import lerobot_policy_mint  # noqa: F401
    from lerobot.processor import ProcessorStepRegistry
    from lerobot_policy_mint.processor_mint import MINTPrepareStateTokenizerProcessorStep

    if not torch.npu.is_available():
        raise RuntimeError("torch.npu is not available")
    torch.npu.set_device(0)
    probe = torch.ones((32, 32), device="npu", dtype=torch.bfloat16)
    torch.npu.synchronize()
    if not torch.isfinite(probe @ probe).all().item():
        raise RuntimeError("NPU bfloat16 matmul returned non-finite values")

    if "mint" not in PreTrainedConfig.get_known_choices():
        raise RuntimeError("MINT policy was not registered")
    if get_policy_class("mint").__name__ != "MINTPolicy":
        raise RuntimeError("MINT policy class resolution failed")

    prompt_step = ProcessorStepRegistry.get("pi05_prepare_state_tokenizer_processor_step")
    expect_legacy_prompt = os.environ.get("MINT_USE_CURRENT_PI05_STATE_PROMPT") != "1"
    if expect_legacy_prompt and prompt_step is not MINTPrepareStateTokenizerProcessorStep:
        raise RuntimeError(
            "The public MINT checkpoint would use the current 8-token PI0.5 state prompt "
            "instead of its LeRobot v0.4.3 32-token training prompt"
        )

    result = {
        "npu_count": torch.npu.device_count(),
        "npu_name": torch.npu.get_device_name(0),
        "mint_registered": True,
        "mint_legacy_pi05_prompt_compatibility": (
            prompt_step is MINTPrepareStateTokenizerProcessorStep
        ),
        "mint_prompt_state_dimensions": 32 if expect_legacy_prompt else 8,
    }

    if args.checkpoint:
        require_file(args.checkpoint / "config.json")
        with (args.checkpoint / "config.json").open() as config_file:
            config = json.load(config_file)
        if config.get("type") != "mint":
            raise ValueError(f"Expected a MINT checkpoint, got type={config.get('type')!r}")
        for filename in ("policy_preprocessor.json", "policy_postprocessor.json"):
            require_file(args.checkpoint / filename)
        if args.require_weights:
            require_file(args.checkpoint / "model.safetensors", minimum_bytes=1_000_000_000)
        result["checkpoint"] = str(args.checkpoint)

    if args.tokenizer:
        require_file(args.tokenizer / "ms_vqvae.pth", minimum_bytes=100_000_000)
        result["tokenizer"] = str(args.tokenizer)

    if args.dataset:
        require_file(args.dataset / "meta" / "info.json")
        with (args.dataset / "meta" / "info.json").open() as info_file:
            dataset_info = json.load(info_file)
        data_files = list((args.dataset / "data").glob("**/*.parquet"))
        video_files = list((args.dataset / "videos").glob("**/*.mp4"))
        incomplete_files = list(args.dataset.glob("**/*.incomplete"))
        if args.require_complete_dataset:
            expected = {
                "total_episodes": 1693,
                "total_frames": 273465,
                "data_files": 377,
                "video_files": 74,
            }
            actual = {
                "total_episodes": dataset_info.get("total_episodes"),
                "total_frames": dataset_info.get("total_frames"),
                "data_files": len(data_files),
                "video_files": len(video_files),
            }
            if actual != expected or incomplete_files:
                raise RuntimeError(
                    "Incomplete lerobot/libero revision "
                    "a1aaacb7f6cd6ee5fb43120f673cebb0cfea7dd4: "
                    f"expected={expected}, actual={actual}, incomplete_files={len(incomplete_files)}"
                )
        result["dataset"] = str(args.dataset)
        result["dataset_total_episodes"] = dataset_info.get("total_episodes")
        result["dataset_total_frames"] = dataset_info.get("total_frames")
        result["dataset_data_files"] = len(data_files)
        result["dataset_video_files"] = len(video_files)
        result["dataset_incomplete_files"] = len(incomplete_files)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
