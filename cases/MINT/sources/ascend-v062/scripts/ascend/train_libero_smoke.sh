#!/usr/bin/env bash

set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

STEPS="${1:-2}"
BATCH_SIZE="${2:-1}"
RUN_NAME="${3:-mint_libero_npu_smoke_$(date +%Y%m%d_%H%M%S)}"
CHECKPOINT="${4:-$MINT_CHECKPOINT}"
EPISODES="${5:-[0]}"
SAVE_CHECKPOINT="${6:-true}"
DATASET="$HF_LEROBOT_HOME/lerobot/libero"
OUTPUT_DIR="$MINT_OUTPUT_ROOT/train/$RUN_NAME"

if ! [[ "$STEPS" =~ ^[1-9][0-9]*$ && "$BATCH_SIZE" =~ ^[1-9][0-9]*$ ]]; then
    echo "STEPS and BATCH_SIZE must be positive integers" >&2
    exit 2
fi
if [[ "$SAVE_CHECKPOINT" != "true" && "$SAVE_CHECKPOINT" != "false" ]]; then
    echo "SAVE_CHECKPOINT must be true or false" >&2
    exit 2
fi
if [[ -e "$OUTPUT_DIR" ]]; then
    echo "Refusing to overwrite existing run directory: $OUTPUT_DIR" >&2
    exit 2
fi

python "$SCRIPT_DIR/preflight_mint.py" \
    --checkpoint "$CHECKPOINT" \
    --dataset "$DATASET" \
    --require-weights

mkdir -p "$(dirname -- "$OUTPUT_DIR")"
LOG_FILE="$OUTPUT_DIR.bootstrap.log"
retain_log() {
    if [[ -f "$LOG_FILE" ]]; then
        mkdir -p "$OUTPUT_DIR"
        mv "$LOG_FILE" "$OUTPUT_DIR/train.log"
    fi
}
trap retain_log EXIT

printf '%s\n' \
    "checkpoint=$CHECKPOINT" \
    "dataset=$DATASET" \
    "episodes=$EPISODES" \
    "output_dir=$OUTPUT_DIR" \
    "steps=$STEPS" \
    "batch_size=$BATCH_SIZE" \
    "save_checkpoint=$SAVE_CHECKPOINT" | tee "$LOG_FILE"
npu-smi info 2>&1 | tee -a "$LOG_FILE"

lerobot-train \
    "--discover_packages_path=lerobot_policy_mint" \
    "--dataset.repo_id=lerobot/libero" \
    "--dataset.root=$DATASET" \
    "--dataset.episodes=$EPISODES" \
    "--dataset.revision=a1aaacb7f6cd6ee5fb43120f673cebb0cfea7dd4" \
    "--dataset.video_backend=pyav" \
    "--dataset.return_uint8=true" \
    "--policy.path=$CHECKPOINT" \
    "--policy.device=npu" \
    "--policy.dtype=bfloat16" \
    "--policy.compile_model=false" \
    "--policy.gradient_checkpointing=true" \
    "--policy.push_to_hub=false" \
    "--policy.optimizer_lr=2e-4" \
    "--policy.scheduler_warmup_steps=1" \
    "--policy.scheduler_decay_steps=$STEPS" \
    "--output_dir=$OUTPUT_DIR" \
    "--job_name=$RUN_NAME" \
    "--steps=$STEPS" \
    "--batch_size=$BATCH_SIZE" \
    "--num_workers=0" \
    "--persistent_workers=false" \
    "--env_eval_freq=0" \
    "--eval_steps=0" \
    "--log_freq=1" \
    "--save_checkpoint=$SAVE_CHECKPOINT" \
    "--save_freq=$STEPS" \
    "--ema.enable=false" \
    "--wandb.enable=false" \
    "--seed=42" 2>&1 | tee -a "$LOG_FILE"
