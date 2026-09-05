#!/usr/bin/env bash

set -eo pipefail

ROOT="${ASCEND_VLA_PERSISTENT_ROOT:?必须先显式设置 ASCEND_VLA_PERSISTENT_ROOT}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RUN_NAME="${RUN_NAME:-mint_official_v043_16npu_30000_20260828}"
OUTPUT_DIR="$ROOT/outputs/mint-v043/train/$RUN_NAME"
FINAL_CHECKPOINT="$OUTPUT_DIR/checkpoints/last/pretrained_model"

env \
    RUN_NAME="$RUN_NAME" \
    NUM_PROCESSES=16 \
    MICRO_BATCH=8 \
    STEPS=30000 \
    SAVE_FREQ=2000 \
    SAVE_CHECKPOINT=true \
    DEVICE_IDS= \
    "$SCRIPT_DIR/train_mint_v043.sh"

if [[ ! -f "$FINAL_CHECKPOINT/model.safetensors" ]]; then
    echo "MINT final checkpoint is missing: $FINAL_CHECKPOINT" >&2
    exit 1
fi

eval_pids=()
"$SCRIPT_DIR/eval_v043_aligned_task_sharded_8npu.sh" \
    mint "$FINAL_CHECKPOINT" "${RUN_NAME}_trained_aligned_50eps" \
    50 4 42 0,1,2,3,4,5,6,7 &
eval_pids+=("$!")

"$SCRIPT_DIR/eval_v043_aligned_task_sharded_8npu.sh" \
    mint "$ROOT/models/mint_libero" "${RUN_NAME}_official_aligned_50eps" \
    50 4 42 8,9,10,11,12,13,14,15 &
eval_pids+=("$!")

eval_status=0
for pid in "${eval_pids[@]}"; do
    if ! wait "$pid"; then
        eval_status=1
    fi
done

if (( eval_status != 0 )); then
    echo "At least one MINT post-training evaluation failed" >&2
    exit "$eval_status"
fi
