#!/usr/bin/env bash

set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

RUN_TAG="${1:-joint_8npu_12h_$(date +%Y%m%d_%H%M%S)}"
DURATION="${2:-12h}"
MINT_MICRO_BATCH="${MINT_MICRO_BATCH:-8}"
PI05_MICRO_BATCH="${PI05_MICRO_BATCH:-16}"
MINT_SAVE_UPDATES="${MINT_SAVE_UPDATES:-200}"
PI05_SAVE_UPDATES="${PI05_SAVE_UPDATES:-100}"
MINT_OPTIMIZER_UPDATES="${MINT_OPTIMIZER_UPDATES:-30000}"
PI05_OPTIMIZER_UPDATES="${PI05_OPTIMIZER_UPDATES:-6000}"
PI05_CHECKPOINT="$MINT_ASCEND_ROOT/models/pi05_libero_base"
DATASET="$HF_LEROBOT_HOME/lerobot/libero"
SESSION_DIR="$LEROBOT_OUTPUT_ROOT/joint_8npu_12h/$RUN_TAG"
PI05_TRAIN="$MINT_ASCEND_ROOT/projects/lerobot-ascend/scripts/ascend/train_libero_reproduction.sh"
MINT_BASE_SHA256="0eb11ca9587678c1d2ef8cf32807c29f8ce53a2bfdfc1aa4a4c96f16fca59b0f"
PI05_BASE_SHA256="21b8711787c4a75861b02cff6aa81675a3a943d32b435a68262ac4461e476ba4"
TOKENIZER_SHA256="f0c4bebe96be6d3db9f45321d16623b56dea78c5772b8205ac7b45cb8c123ccc"

for value in "$MINT_MICRO_BATCH" "$PI05_MICRO_BATCH"; do
    if ! [[ "$value" =~ ^[1-9][0-9]*$ ]]; then
        echo "Micro batches must be positive integers" >&2
        exit 2
    fi
done
MINT_SAMPLES_PER_MICRO_STEP=$((4 * MINT_MICRO_BATCH))
PI05_SAMPLES_PER_MICRO_STEP=$((4 * PI05_MICRO_BATCH))
if (( 128 % MINT_SAMPLES_PER_MICRO_STEP != 0 || 256 % PI05_SAMPLES_PER_MICRO_STEP != 0 )); then
    echo "Official global batches must be divisible by four processes times the micro batch" >&2
    exit 2
fi
MINT_GRAD_ACCUM=$((128 / MINT_SAMPLES_PER_MICRO_STEP))
PI05_GRAD_ACCUM=$((256 / PI05_SAMPLES_PER_MICRO_STEP))

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

if [[ -e "$SESSION_DIR" ]]; then
    echo "Refusing to overwrite existing session directory: $SESSION_DIR" >&2
    exit 2
fi
python "$SCRIPT_DIR/preflight_mint.py" \
    --tokenizer "$MINT_TOKENIZER" \
    --dataset "$DATASET" \
    --require-complete-dataset
NPU_COUNT="$(python -c 'import torch; print(torch.npu.device_count())')"
if (( NPU_COUNT < 8 )); then
    echo "Eight visible NPUs are required, found $NPU_COUNT" >&2
    exit 2
fi
for required in \
    "$MINT_PI05_BASE/model.safetensors" \
    "$PI05_CHECKPOINT/model.safetensors" \
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
verify_sha256 "$MINT_PI05_BASE/model.safetensors" "$MINT_BASE_SHA256"
verify_sha256 "$PI05_CHECKPOINT/model.safetensors" "$PI05_BASE_SHA256"
verify_sha256 "$MINT_TOKENIZER/ms_vqvae.pth" "$TOKENIZER_SHA256"

mkdir -p "$SESSION_DIR"
printf '%s\n' \
    "run_tag=$RUN_TAG" \
    "duration=$DURATION" \
    "npu_count=$NPU_COUNT" \
    "mint_visible_devices=0,1,2,3" \
    "pi05_visible_devices=4,5,6,7" \
    "mint_num_processes=4" \
    "pi05_num_processes=4" \
    "mint_micro_batch_per_process=$MINT_MICRO_BATCH" \
    "pi05_micro_batch_per_process=$PI05_MICRO_BATCH" \
    "mint_gradient_accumulation=$MINT_GRAD_ACCUM" \
    "pi05_gradient_accumulation=$PI05_GRAD_ACCUM" \
    "mint_effective_global_batch=128" \
    "pi05_effective_global_batch=256" \
    "mint_recipe_source=arXiv:2602.08602v3 Appendix Table VI" \
    "pi05_recipe=published_v044" \
    "pi05_recipe_source=pi05_libero_finetuned_v044 train_config.json" \
    "mint_optimizer_updates=$MINT_OPTIMIZER_UPDATES" \
    "pi05_optimizer_updates=$PI05_OPTIMIZER_UPDATES" \
    "mint_save_every_updates=$MINT_SAVE_UPDATES" \
    "pi05_save_every_updates=$PI05_SAVE_UPDATES" \
    "dataset=$DATASET" \
    "mint_base=$MINT_PI05_BASE" \
    "mint_base_sha256=$MINT_BASE_SHA256" \
    "mint_tokenizer=$MINT_TOKENIZER" \
    "mint_tokenizer_sha256=$TOKENIZER_SHA256" \
    "pi05_base=$PI05_CHECKPOINT" \
    "pi05_base_sha256=$PI05_BASE_SHA256" \
    "started_at=$(date --iso-8601=seconds)" \
    >"$SESSION_DIR/manifest.txt"
npu-smi info >"$SESSION_DIR/npu_before.txt" 2>&1

nohup timeout --signal=TERM --kill-after=5m "$DURATION" \
    env ASCEND_RT_VISIBLE_DEVICES=0,1,2,3 \
    "$SCRIPT_DIR/train_libero_reproduction.sh" \
    4 "$MINT_MICRO_BATCH" "${RUN_TAG}_mint" \
    "$MINT_OPTIMIZER_UPDATES" "$MINT_SAVE_UPDATES" \
    >"$SESSION_DIR/mint_launcher.log" 2>&1 </dev/null &
MINT_PID=$!

nohup timeout --signal=TERM --kill-after=5m "$DURATION" \
    env ASCEND_RT_VISIBLE_DEVICES=4,5,6,7 PI05_RECIPE=published_v044 \
    "$PI05_TRAIN" \
    4 "$PI05_MICRO_BATCH" "${RUN_TAG}_pi05" "$PI05_CHECKPOINT" \
    "$PI05_OPTIMIZER_UPDATES" "$PI05_SAVE_UPDATES" \
    >"$SESSION_DIR/pi05_launcher.log" 2>&1 </dev/null &
PI05_PID=$!

nohup timeout --signal=TERM "$DURATION" \
    "$SCRIPT_DIR/collect_npu_telemetry.sh" "$SESSION_DIR" "$MINT_PID" "$PI05_PID" \
    >"$SESSION_DIR/telemetry_launcher.log" 2>&1 </dev/null &
TELEMETRY_PID=$!

printf '%s\n' "$MINT_PID" >"$SESSION_DIR/mint.pid"
printf '%s\n' "$PI05_PID" >"$SESSION_DIR/pi05.pid"
printf '%s\n' "$TELEMETRY_PID" >"$SESSION_DIR/telemetry.pid"
printf 'session_dir=%s\nmint_pid=%s\npi05_pid=%s\ntelemetry_pid=%s\n' \
    "$SESSION_DIR" "$MINT_PID" "$PI05_PID" "$TELEMETRY_PID"
