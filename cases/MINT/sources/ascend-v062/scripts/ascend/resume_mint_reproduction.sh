#!/usr/bin/env bash

set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

PRETRAINED_DIR="${1:?Usage: $0 PRETRAINED_MODEL_DIR TARGET_OPTIMIZER_UPDATES DEVICE_IDS_CSV [RUN_NAME]}"
TARGET_OPTIMIZER_UPDATES="${2:?Usage: $0 PRETRAINED_MODEL_DIR TARGET_OPTIMIZER_UPDATES DEVICE_IDS_CSV [RUN_NAME]}"
DEVICE_IDS_CSV="${3:?Usage: $0 PRETRAINED_MODEL_DIR TARGET_OPTIMIZER_UPDATES DEVICE_IDS_CSV [RUN_NAME]}"
RUN_NAME="${4:-mint_libero_npu_resume_$(date +%Y%m%d_%H%M%S)}"
TRAIN_CONFIG="$PRETRAINED_DIR/train_config.json"

if ! [[ "$TARGET_OPTIMIZER_UPDATES" =~ ^[1-9][0-9]*$ ]]; then
    echo "TARGET_OPTIMIZER_UPDATES must be a positive integer" >&2
    exit 2
fi
if [[ ! -f "$TRAIN_CONFIG" ]]; then
    echo "Missing checkpoint training config: $TRAIN_CONFIG" >&2
    exit 2
fi

read -r MICRO_BATCH GRAD_ACCUM NUM_PROCESSES < <(
    python - "$TRAIN_CONFIG" <<'PY'
import json
import sys

config = json.load(open(sys.argv[1], encoding="utf-8"))
print(
    config["batch_size"],
    config["accelerator"]["gradient_accumulation"]["steps"],
    config["parallelism"]["dp_replicate"],
)
PY
)
IFS=',' read -r -a DEVICE_IDS <<<"$DEVICE_IDS_CSV"
if (( ${#DEVICE_IDS[@]} != NUM_PROCESSES )); then
    echo "Checkpoint requires $NUM_PROCESSES devices, got ${#DEVICE_IDS[@]}" >&2
    exit 2
fi
declare -A SEEN_DEVICES=()
for device in "${DEVICE_IDS[@]}"; do
    if ! [[ "$device" =~ ^[0-9]+$ ]] || [[ -n "${SEEN_DEVICES[$device]:-}" ]]; then
        echo "NPU device IDs must be unique non-negative integers: $DEVICE_IDS_CSV" >&2
        exit 2
    fi
    SEEN_DEVICES[$device]=1
done
if (( MICRO_BATCH * GRAD_ACCUM * NUM_PROCESSES != 128 )); then
    echo "Checkpoint does not preserve the official global batch 128" >&2
    exit 2
fi

TARGET_MICRO_STEPS=$((TARGET_OPTIMIZER_UPDATES * GRAD_ACCUM))
printf '%s\n' \
    "checkpoint=$PRETRAINED_DIR" \
    "target_optimizer_updates=$TARGET_OPTIMIZER_UPDATES" \
    "target_micro_steps=$TARGET_MICRO_STEPS" \
    "micro_batch_per_process=$MICRO_BATCH" \
    "gradient_accumulation_steps=$GRAD_ACCUM" \
    "num_processes=$NUM_PROCESSES" \
    "effective_global_batch=128" \
    "visible_devices=$DEVICE_IDS_CSV"

ASCEND_RT_VISIBLE_DEVICES="$DEVICE_IDS_CSV" "$SCRIPT_DIR/resume_libero_train.sh" \
    "$PRETRAINED_DIR" "$TARGET_MICRO_STEPS" "$NUM_PROCESSES" "$RUN_NAME"
