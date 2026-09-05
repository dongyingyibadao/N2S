#!/usr/bin/env python

import argparse
import json
import math
from pathlib import Path
import statistics
import time

import torch
import torch_npu  # noqa: F401

from lerobot_policy_mint.configuration_mint import MINTConfig
from lerobot.configs.policies import PreTrainedConfig
from lerobot_policy_mint.modeling_mint import MINTPolicy, MINTPytorch


def synchronize() -> None:
    torch.npu.synchronize()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("inference", "training"), default="inference")
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--images", type=int, default=2)
    parser.add_argument("--token-length", type=int, default=32)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--optimizer-step", action="store_true")
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args()

    if (
        args.batch_size < 1
        or args.images < 1
        or args.token_length < 1
        or args.warmup < 0
        or args.repeats < 1
    ):
        raise ValueError("batch size, image count, and token length must be positive")
    if not torch.npu.is_available():
        raise RuntimeError("torch.npu is not available")
    if args.optimizer_step and args.mode != "training":
        raise ValueError("--optimizer-step requires --mode=training")

    torch.manual_seed(42)
    torch.npu.set_device(0)
    device = torch.device("npu:0")
    build_started = time.perf_counter()
    if args.checkpoint is None:
        config = MINTConfig(
            device="npu",
            dtype="bfloat16",
            compile_model=False,
            gradient_checkpointing=args.mode == "training",
        )
        model = MINTPytorch(config).to(device)
        scope = "random-weight structure-only smoke; not a quality result"
    else:
        config = PreTrainedConfig.from_pretrained(
            args.checkpoint,
            cli_overrides=[
                "--device=npu",
                "--compile_model=false",
                f"--gradient_checkpointing={str(args.mode == 'training').lower()}",
            ],
        )
        if config.type != "mint":
            raise ValueError(f"Expected MINT checkpoint, got {config.type!r}")
        policy = MINTPolicy.from_pretrained(args.checkpoint, config=config)
        model = policy.model
        scope = f"pretrained checkpoint: {args.checkpoint}"
    synchronize()
    build_seconds = time.perf_counter() - build_started

    images = [
        torch.randn(
            args.batch_size,
            3,
            224,
            224,
            device=device,
            dtype=torch.float32,
        )
        for _ in range(args.images)
    ]
    image_masks = [torch.ones(args.batch_size, device=device, dtype=torch.bool) for _ in images]
    tokens = torch.zeros(
        args.batch_size,
        args.token_length,
        device=device,
        dtype=torch.long,
    )
    token_masks = torch.ones_like(tokens, dtype=torch.bool)

    if args.mode == "inference":
        model.eval()
        with torch.no_grad():
            for _ in range(args.warmup):
                model.sample_actions(images, image_masks, tokens, token_masks, sample_top_k=1)
                synchronize()
            run_times = []
            for _ in range(args.repeats):
                run_started = time.perf_counter()
                action_chunk, intention = model.sample_actions(
                    images,
                    image_masks,
                    tokens,
                    token_masks,
                    sample_top_k=1,
                )
                synchronize()
                run_times.append(time.perf_counter() - run_started)
        loss = None
    else:
        model.train()
        model.gradient_checkpointing_enable()
        optimizer = None
        if args.optimizer_step:
            optimizer = torch.optim.AdamW(
                (parameter for parameter in model.parameters() if parameter.requires_grad),
                lr=2e-4,
                betas=(0.9, 0.95),
                eps=1e-8,
                weight_decay=0.01,
            )
        actions = torch.randn(
            args.batch_size,
            config.chunk_size,
            config.max_action_dim,
            device=device,
            dtype=torch.float32,
        ).clamp(-1, 1)
        run_started = time.perf_counter()
        loss = model(images, image_masks, tokens, token_masks, actions).mean()
        loss.backward()
        finite_output_gradient = torch.isfinite(model.vq_code_out_proj.weight.grad).all().item()
        if optimizer is not None:
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)
        synchronize()
        run_times = [time.perf_counter() - run_started]
        action_chunk = None
        intention = None

    result = {
        "scope": scope,
        "mode": args.mode,
        "device": torch.npu.get_device_name(0),
        "batch_size": args.batch_size,
        "image_count": args.images,
        "image_dtype": str(images[0].dtype),
        "token_length": args.token_length,
        "build_seconds": round(build_seconds, 4),
        "warmup_runs": args.warmup if args.mode == "inference" else 0,
        "timed_runs": len(run_times),
        "optimizer_step": args.optimizer_step,
        "run_seconds_mean": round(statistics.mean(run_times), 4),
        "run_seconds_median": round(statistics.median(run_times), 4),
        "run_seconds_p95": round(sorted(run_times)[math.ceil(0.95 * len(run_times)) - 1], 4),
        "run_seconds_min": round(min(run_times), 4),
        "run_seconds_max": round(max(run_times), 4),
        "max_memory_gib": round(torch.npu.max_memory_allocated() / 1024**3, 4),
    }
    if action_chunk is not None and intention is not None:
        result["action_shape"] = list(action_chunk.shape)
        result["intention_shape"] = list(intention.shape)
        result["finite_actions"] = torch.isfinite(action_chunk).all().item()
    if loss is not None:
        result["loss"] = loss.item()
        result["finite_loss"] = torch.isfinite(loss).item()
        result["finite_output_gradient"] = finite_output_gradient
    rendered = json.dumps(result, indent=2)
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
