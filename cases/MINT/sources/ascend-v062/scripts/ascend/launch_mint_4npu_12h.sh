#!/usr/bin/env bash

set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

RUN_TAG="${1:-mint_4npu_12h_$(date +%Y%m%d_%H%M%S)}"
DURATION="${2:-12h}"
DEVICE_IDS_CSV="${3:-0,1,2,3}"
NUM_PROCESSES="${MINT_NUM_PROCESSES:-4}"
MICRO_BATCH="${MINT_MICRO_BATCH:-8}"
SAVE_UPDATES="${MINT_SAVE_UPDATES:-1000}"
OPTIMIZER_UPDATES="${MINT_OPTIMIZER_UPDATES:-30000}"
TARGET_GLOBAL_BATCH=128
DATASET="$HF_LEROBOT_HOME/lerobot/libero"
TRAIN_RUN_NAME="${RUN_TAG}_mint"
TRAIN_OUTPUT="$MINT_OUTPUT_ROOT/train/$TRAIN_RUN_NAME"
SESSION_DIR="$LEROBOT_OUTPUT_ROOT/mint_${NUM_PROCESSES}npu_12h/$RUN_TAG"
BASE_SHA256="0eb11ca9587678c1d2ef8cf32807c29f8ce53a2bfdfc1aa4a4c96f16fca59b0f"
TOKENIZER_SHA256="f0c4bebe96be6d3db9f45321d16623b56dea78c5772b8205ac7b45cb8c123ccc"
IFS=',' read -r -a DEVICE_IDS <<<"$DEVICE_IDS_CSV"

for value in "$NUM_PROCESSES" "$MICRO_BATCH" "$SAVE_UPDATES" "$OPTIMIZER_UPDATES"; do
    if ! [[ "$value" =~ ^[1-9][0-9]*$ ]]; then
        echo "Batch size, save interval, and optimizer updates must be positive integers" >&2
        exit 2
    fi
done
if (( ${#DEVICE_IDS[@]} != NUM_PROCESSES )); then
    echo "Expected $NUM_PROCESSES comma-separated NPU device IDs, got ${#DEVICE_IDS[@]}" >&2
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
SAMPLES_PER_MICRO_STEP=$((NUM_PROCESSES * MICRO_BATCH))
if (( TARGET_GLOBAL_BATCH % SAMPLES_PER_MICRO_STEP != 0 )); then
    echo "Global batch 128 must be divisible by process count times micro batch" >&2
    exit 2
fi
GRAD_ACCUM=$((TARGET_GLOBAL_BATCH / SAMPLES_PER_MICRO_STEP))

verify_sha256() {
    local path="$1"
    local expected="$2"
    local actual
    actual="$(sha256sum "$path" | cut -d ' ' -f 1)"
    if [[ "$actual" != "$expected" ]]; then
        echo "SHA256 mismatch for $path: expected=$expected actual=$actual" >&2
        exit 2
    fi
}

if [[ -e "$SESSION_DIR" || -e "$TRAIN_OUTPUT" ]]; then
    echo "Refusing to overwrite an existing session or training directory" >&2
    exit 2
fi
python "$SCRIPT_DIR/preflight_mint.py" \
    --tokenizer "$MINT_TOKENIZER" \
    --dataset "$DATASET" \
    --require-complete-dataset
NPU_COUNT="$(python -c 'import torch; print(torch.npu.device_count())')"
if (( NPU_COUNT < NUM_PROCESSES )); then
    echo "$NUM_PROCESSES visible NPUs are required, found $NPU_COUNT" >&2
    exit 2
fi
for device in "${DEVICE_IDS[@]}"; do
    if (( device >= NPU_COUNT )); then
        echo "NPU device $device is outside the visible range 0-$((NPU_COUNT - 1))" >&2
        exit 2
    fi
done
for required in \
    "$MINT_PI05_BASE/model.safetensors" \
    "$MINT_TOKENIZER/ms_vqvae.pth" \
    "$DATASET/meta/info.json"; do
    if [[ ! -f "$required" ]]; then
        echo "Required training asset is incomplete: $required" >&2
        exit 2
    fi
done
if (( $(find "$DATASET" -type f -name '*.incomplete' | wc -l) > 0 )); then
    echo "LIBERO dataset still contains incomplete downloads" >&2
    exit 2
fi
verify_sha256 "$MINT_PI05_BASE/model.safetensors" "$BASE_SHA256"
verify_sha256 "$MINT_TOKENIZER/ms_vqvae.pth" "$TOKENIZER_SHA256"

mkdir -p "$SESSION_DIR"
printf '%s\n' \
    "run_tag=$RUN_TAG" \
    "hostname=$(hostname)" \
    "duration=$DURATION" \
    "visible_devices=$DEVICE_IDS_CSV" \
    "num_processes=$NUM_PROCESSES" \
    "micro_batch_per_process=$MICRO_BATCH" \
    "gradient_accumulation_steps=$GRAD_ACCUM" \
    "effective_global_batch=$TARGET_GLOBAL_BATCH" \
    "optimizer_updates=$OPTIMIZER_UPDATES" \
    "trainer_micro_steps=$((OPTIMIZER_UPDATES * GRAD_ACCUM))" \
    "save_every_optimizer_updates=$SAVE_UPDATES" \
    "recipe_source=arXiv:2602.08602v3_Appendix_Table_VI" \
    "optimizer=AdamW" \
    "learning_rate=2e-4" \
    "betas=0.9,0.95" \
    "weight_decay=0.01" \
    "chunk_size=16" \
    "scheduler=cosine_decay_with_warmup" \
    "scheduler_warmup_optimizer_updates=1000" \
    "scheduler_decay_optimizer_updates=30000" \
    "dataset=$DATASET" \
    "dataset_revision=a1aaacb7f6cd6ee5fb43120f673cebb0cfea7dd4" \
    "dataset_frames=273465" \
    "dataset_episodes=1693" \
    "initialization=$MINT_PI05_BASE" \
    "initialization_sha256=$BASE_SHA256" \
    "initialization_scope=pi05_PaliGemma_backbone_only" \
    "action_expert_initialization=random_as_specified_by_paper" \
    "tokenizer=$MINT_TOKENIZER/ms_vqvae.pth" \
    "tokenizer_sha256=$TOKENIZER_SHA256" \
    "training_output=$TRAIN_OUTPUT" \
    "resume_script=$SCRIPT_DIR/resume_libero_train.sh" \
    "resume_by_optimizer_update_script=$SCRIPT_DIR/resume_mint_reproduction.sh" \
    "started_at=$(date --iso-8601=seconds)" \
    >"$SESSION_DIR/manifest.txt"
sha256sum \
    "$SCRIPT_DIR/launch_mint_4npu_12h.sh" \
    "$SCRIPT_DIR/train_libero_reproduction.sh" \
    "$SCRIPT_DIR/resume_libero_train.sh" \
    "$SCRIPT_DIR/resume_mint_reproduction.sh" \
    >"$SESSION_DIR/script_sha256.txt"
npu-smi info >"$SESSION_DIR/npu_before.txt" 2>&1

nohup timeout --signal=TERM --kill-after=5m "$DURATION" \
    env ASCEND_RT_VISIBLE_DEVICES="$DEVICE_IDS_CSV" \
    "$SCRIPT_DIR/train_libero_reproduction.sh" \
    "$NUM_PROCESSES" "$MICRO_BATCH" "$TRAIN_RUN_NAME" "$OPTIMIZER_UPDATES" "$SAVE_UPDATES" true \
    >"$SESSION_DIR/mint_launcher.log" 2>&1 </dev/null &
MINT_PID=$!

nohup timeout --signal=TERM "$DURATION" \
    "$SCRIPT_DIR/collect_npu_telemetry.sh" "$SESSION_DIR" "$MINT_PID" "$MINT_PID" \
    >"$SESSION_DIR/telemetry_launcher.log" 2>&1 </dev/null &
TELEMETRY_PID=$!

printf '%s\n' "$MINT_PID" >"$SESSION_DIR/mint.pid"
printf '%s\n' "$TELEMETRY_PID" >"$SESSION_DIR/telemetry.pid"
printf 'session_dir=%s\nmint_pid=%s\ntelemetry_pid=%s\n' \
    "$SESSION_DIR" "$MINT_PID" "$TELEMETRY_PID"
