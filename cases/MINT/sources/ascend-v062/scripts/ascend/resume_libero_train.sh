#!/usr/bin/env bash

set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

PRETRAINED_DIR="${1:?Usage: $0 PRETRAINED_MODEL_DIR TARGET_STEPS NUM_PROCESSES [RUN_NAME]}"
TARGET_STEPS="${2:?Usage: $0 PRETRAINED_MODEL_DIR TARGET_STEPS NUM_PROCESSES [RUN_NAME]}"
NUM_PROCESSES="${3:?Usage: $0 PRETRAINED_MODEL_DIR TARGET_STEPS NUM_PROCESSES [RUN_NAME]}"
RUN_NAME="${4:-mint_libero_npu_resume_$(date +%Y%m%d_%H%M%S)}"
OUTPUT_DIR="$MINT_OUTPUT_ROOT/train/$RUN_NAME"
TRAIN_CONFIG="$PRETRAINED_DIR/train_config.json"
TRAINING_STATE="$(dirname -- "$PRETRAINED_DIR")/training_state"

if [[ ! -f "$TRAIN_CONFIG" || ! -f "$TRAINING_STATE/training_step.json" ]]; then
    echo "Incomplete resumable checkpoint: $PRETRAINED_DIR" >&2
    exit 2
fi
if [[ -e "$OUTPUT_DIR" ]]; then
    echo "Refusing to overwrite existing run directory: $OUTPUT_DIR" >&2
    exit 2
fi

mkdir -p "$OUTPUT_DIR"
LOG_FILE="$OUTPUT_DIR/resume.log"
printf '%s\n' \
    "pretrained_dir=$PRETRAINED_DIR" \
    "training_state=$TRAINING_STATE" \
    "target_steps=$TARGET_STEPS" \
    "num_processes=$NUM_PROCESSES" \
    "output_dir=$OUTPUT_DIR" | tee "$LOG_FILE"

torchrun --standalone --nproc-per-node="$NUM_PROCESSES" "$(command -v lerobot-train)" \
    "--discover_packages_path=lerobot_policy_mint" \
    "--config_path=$TRAIN_CONFIG" \
    "--resume=true" \
    "--steps=$TARGET_STEPS" \
    "--output_dir=$OUTPUT_DIR" \
    "--job_name=$RUN_NAME" \
    "--save_checkpoint=true" \
    "--wandb.enable=false" 2>&1 | tee -a "$LOG_FILE"
