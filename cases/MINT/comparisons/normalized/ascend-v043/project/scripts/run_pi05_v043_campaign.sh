#!/usr/bin/env bash

set -eo pipefail

ROOT="${ASCEND_VLA_PERSISTENT_ROOT:?必须先显式设置 ASCEND_VLA_PERSISTENT_ROOT}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RUN_NAME="${RUN_NAME:-pi05_libero_base_v043_8npu_6000_20260828}"
OUTPUT_DIR="$ROOT/outputs/train-v043/$RUN_NAME"
FINAL_CHECKPOINT="$OUTPUT_DIR/checkpoints/last/pretrained_model"

env \
    RUN_NAME="$RUN_NAME" \
    NUM_PROCESSES=8 \
    MICRO_BATCH=32 \
    STEPS=6000 \
    SAVE_FREQ=2000 \
    SAVE_CHECKPOINT=true \
    DEVICE_IDS= \
    "$SCRIPT_DIR/train_pi05_v043.sh"

if [[ ! -f "$FINAL_CHECKPOINT/model.safetensors" ]]; then
    echo "PI0.5 final checkpoint is missing: $FINAL_CHECKPOINT" >&2
    exit 1
fi

"$SCRIPT_DIR/eval_v043_aligned_task_sharded_8npu.sh" \
    pi05 "$FINAL_CHECKPOINT" "${RUN_NAME}_trained_aligned_50eps" 50 10 1000 0,1,2,3,4,5,6,7

"$SCRIPT_DIR/eval_v043_aligned_task_sharded_8npu.sh" \
    pi05 "$ROOT/models/pi05_libero_finetuned" \
    "${RUN_NAME}_official_v044_aligned_50eps" 50 10 1000 0,1,2,3,4,5,6,7
