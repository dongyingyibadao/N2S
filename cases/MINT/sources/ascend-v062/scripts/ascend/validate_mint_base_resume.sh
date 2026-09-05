#!/usr/bin/env bash

set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

RUN_NAME="${1:-mint_base_resume_validation_$(date +%Y%m%d_%H%M%S)}"
BASE_CHECKPOINT="${2:-$MINT_PI05_BASE}"
SMOKE_STEPS="${3:-2}"
RESUME_TARGET_STEPS="${4:-3}"
DATASET="$HF_LEROBOT_HOME/lerobot/libero"
RESULT_DIR="$MINT_OUTPUT_ROOT/validation/$RUN_NAME"
SMOKE_RUN="${RUN_NAME}_smoke"
RESUME_RUN="${RUN_NAME}_resume"
SMOKE_OUTPUT="$MINT_OUTPUT_ROOT/train/$SMOKE_RUN"

for value in "$SMOKE_STEPS" "$RESUME_TARGET_STEPS"; do
    if ! [[ "$value" =~ ^[1-9][0-9]*$ ]]; then
        echo "Smoke and resume steps must be positive integers" >&2
        exit 2
    fi
done
if (( RESUME_TARGET_STEPS <= SMOKE_STEPS )); then
    echo "Resume target must be greater than smoke steps" >&2
    exit 2
fi
if [[ -e "$RESULT_DIR" || -e "$SMOKE_OUTPUT" ]]; then
    echo "Refusing to overwrite an existing validation or training directory" >&2
    exit 2
fi

mkdir -p "$RESULT_DIR" "$(dirname -- "$SMOKE_OUTPUT")"
printf '%s\n' \
    "initialization=$BASE_CHECKPOINT" \
    "initialization_scope=pi05_PaliGemma_backbone_only" \
    "action_expert_initialization=random" \
    "tokenizer=$MINT_TOKENIZER/ms_vqvae.pth" \
    "dataset=$DATASET" \
    "dataset_episodes=[0]" \
    "smoke_steps=$SMOKE_STEPS" \
    "resume_target_steps=$RESUME_TARGET_STEPS" \
    "smoke_run=$SMOKE_RUN" \
    "resume_run=$RESUME_RUN" \
    >"$RESULT_DIR/manifest.txt"

python "$MINT_ASCEND_ROOT/projects/lerobot-ascend/scripts/ascend/preflight_pi05_train.py" \
    --checkpoint "$BASE_CHECKPOINT" \
    --dataset "$DATASET" \
    --output-dir "$SMOKE_OUTPUT" \
    >"$RESULT_DIR/pi05_base_preflight.json"
python "$SCRIPT_DIR/preflight_mint.py" \
    --tokenizer "$MINT_TOKENIZER" \
    --dataset "$DATASET" \
    --require-complete-dataset \
    >"$RESULT_DIR/mint_preflight.json"

lerobot-train \
    "--discover_packages_path=lerobot_policy_mint" \
    "--dataset.repo_id=lerobot/libero" \
    "--dataset.root=$DATASET" \
    "--dataset.episodes=[0]" \
    "--dataset.revision=a1aaacb7f6cd6ee5fb43120f673cebb0cfea7dd4" \
    "--dataset.video_backend=pyav" \
    "--dataset.return_uint8=true" \
    "--policy.type=mint" \
    "--policy.pretrained_path=$BASE_CHECKPOINT" \
    "--policy.vqvae_name_or_path=$MINT_TOKENIZER/ms_vqvae.pth" \
    "--policy.device=npu" \
    "--policy.dtype=bfloat16" \
    "--policy.compile_model=false" \
    "--policy.gradient_checkpointing=true" \
    "--policy.push_to_hub=false" \
    "--policy.chunk_size=16" \
    "--use_policy_training_preset=false" \
    "--optimizer.type=adamw" \
    "--optimizer.lr=2e-4" \
    "--optimizer.betas=[0.9,0.95]" \
    "--optimizer.eps=1e-8" \
    "--optimizer.weight_decay=0.01" \
    "--optimizer.grad_clip_norm=1.0" \
    "--scheduler.type=cosine_decay_with_warmup" \
    "--scheduler.num_warmup_steps=1" \
    "--scheduler.num_decay_steps=$SMOKE_STEPS" \
    "--scheduler.peak_lr=2e-4" \
    "--scheduler.decay_lr=2e-5" \
    "--output_dir=$SMOKE_OUTPUT" \
    "--job_name=$SMOKE_RUN" \
    "--steps=$SMOKE_STEPS" \
    "--batch_size=1" \
    "--num_workers=0" \
    "--persistent_workers=false" \
    "--env_eval_freq=0" \
    "--eval_steps=0" \
    "--log_freq=1" \
    "--save_checkpoint=true" \
    "--save_freq=$SMOKE_STEPS" \
    "--ema.enable=false" \
    "--wandb.enable=false" \
    "--seed=42" \
    >"$RESULT_DIR/smoke_train.log" 2>&1

SMOKE_CHECKPOINT="$SMOKE_OUTPUT/checkpoints/$(printf '%06d' "$SMOKE_STEPS")/pretrained_model"
if [[ ! -f "$SMOKE_CHECKPOINT/model.safetensors" ]]; then
    echo "Smoke checkpoint was not saved at the expected path: $SMOKE_CHECKPOINT" >&2
    exit 1
fi

"$SCRIPT_DIR/resume_libero_train.sh" \
    "$SMOKE_CHECKPOINT" "$RESUME_TARGET_STEPS" 1 "$RESUME_RUN" \
    >"$RESULT_DIR/resume_launcher.log" 2>&1

RESUMED_CHECKPOINT="$MINT_OUTPUT_ROOT/train/$RESUME_RUN/checkpoints/$(printf '%06d' "$RESUME_TARGET_STEPS")/pretrained_model"
if [[ ! -f "$RESUMED_CHECKPOINT/model.safetensors" ]]; then
    echo "Resumed checkpoint was not saved at the expected path: $RESUMED_CHECKPOINT" >&2
    exit 1
fi

python "$SCRIPT_DIR/smoke_mint_model.py" \
    --checkpoint "$RESUMED_CHECKPOINT" \
    --warmup 1 \
    --repeats 3 \
    --output-json "$RESULT_DIR/reload_inference.json" \
    >"$RESULT_DIR/reload_inference.log" 2>&1
python - "$RESULT_DIR/reload_inference.json" <<'PY'
import json
import math
import sys

result = json.load(open(sys.argv[1], encoding="utf-8"))
if not result.get("finite_actions") or not math.isfinite(result["run_seconds_mean"]):
    raise RuntimeError(f"Invalid resumed MINT inference result: {result}")
PY

printf '%s\n' \
    "smoke_checkpoint=$SMOKE_CHECKPOINT" \
    "resumed_checkpoint=$RESUMED_CHECKPOINT" \
    "status=passed" \
    >"$RESULT_DIR/result.txt"
