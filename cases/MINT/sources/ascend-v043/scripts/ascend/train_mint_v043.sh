#!/usr/bin/env bash

set -eo pipefail

ROOT="${ASCEND_VLA_PERSISTENT_ROOT:?必须先显式设置 ASCEND_VLA_PERSISTENT_ROOT}"
if [[ -f /opt/ascend-vla/activate-v043.sh ]]; then
    V043_ENV=/opt/ascend-vla/activate-v043.sh
else
    V043_ENV="$ROOT/projects/lerobot-v043-ascend/scripts/ascend/env.sh"
fi

if [[ ! -f "$V043_ENV" ]]; then
    echo "Missing LeRobot 0.4.3 environment: $V043_ENV" >&2
    exit 2
fi
source "$V043_ENV"
set -u

NUM_PROCESSES="${NUM_PROCESSES:-16}"
MICRO_BATCH="${MICRO_BATCH:-8}"
STEPS="${STEPS:-30000}"
SAVE_FREQ="${SAVE_FREQ:-2000}"
SAVE_CHECKPOINT="${SAVE_CHECKPOINT:-true}"
DEVICE_IDS="${DEVICE_IDS:-}"
RUN_NAME="${RUN_NAME:-mint_official_v043_16npu_30000}"

DATASET="$ROOT/datasets/lerobot/libero"
PI05_BASE="${MINT_INIT_PATH:-$ROOT/models/compat/pi05_base_for_mint_v043}"
TOKENIZER="$ROOT/models/mint_tokenizer_libero/ms_vqvae.pth"
OUTPUT_DIR="$ROOT/outputs/mint-v043/train/$RUN_NAME"
LOG_FILE="$OUTPUT_DIR.bootstrap.log"

for value in "$NUM_PROCESSES" "$MICRO_BATCH" "$STEPS" "$SAVE_FREQ"; do
    if ! [[ "$value" =~ ^[1-9][0-9]*$ ]]; then
        echo "NUM_PROCESSES, MICRO_BATCH, STEPS, and SAVE_FREQ must be positive integers" >&2
        exit 2
    fi
done
if (( NUM_PROCESSES * MICRO_BATCH != 128 )); then
    echo "MINT reproduction requires global batch 128; got $((NUM_PROCESSES * MICRO_BATCH))" >&2
    exit 2
fi
if [[ -e "$OUTPUT_DIR" ]]; then
    echo "Refusing to overwrite existing output: $OUTPUT_DIR" >&2
    exit 2
fi
if [[ ! -f "$PI05_BASE/model.safetensors" || ! -f "$TOKENIZER" ]]; then
    echo "MINT base checkpoint or tokenizer is incomplete" >&2
    exit 2
fi

mkdir -p "$(dirname -- "$OUTPUT_DIR")"
if [[ -n "$DEVICE_IDS" ]]; then
    export ASCEND_RT_VISIBLE_DEVICES="$DEVICE_IDS"
else
    unset ASCEND_RT_VISIBLE_DEVICES || true
fi
export HCCL_CONNECT_TIMEOUT="${HCCL_CONNECT_TIMEOUT:-1800}"

retain_log() {
    if [[ -d "$OUTPUT_DIR" && -f "$LOG_FILE" ]]; then
        mv "$LOG_FILE" "$OUTPUT_DIR/train.log"
    fi
}
trap retain_log EXIT

{
    printf '%s\n' \
        "framework=lerobot-0.4.3" \
        "initialization=$PI05_BASE" \
        "initialization_scope=pi05_PaliGemma_backbone_only" \
        "action_expert_initialization=random" \
        "tokenizer=$TOKENIZER" \
        "dataset=$DATASET" \
        "output_dir=$OUTPUT_DIR" \
        "num_processes=$NUM_PROCESSES" \
        "micro_batch_per_process=$MICRO_BATCH" \
        "effective_global_batch=$((NUM_PROCESSES * MICRO_BATCH))" \
        "optimizer_updates=$STEPS" \
        "device_ids=${DEVICE_IDS:-all_container_visible_devices}"
    npu-smi info
} >"$LOG_FILE" 2>&1

TRAIN_ARGS=(
    "--discover_packages_path=lerobot_policy_mint"
    "--dataset.repo_id=lerobot/libero"
    "--dataset.root=$DATASET"
    "--dataset.episodes=null"
    "--dataset.video_backend=pyav"
    "--policy.type=mint"
    "--policy.pretrained_path=$PI05_BASE"
    "--policy.vqvae_name_or_path=$TOKENIZER"
    "--policy.device=npu"
    "--policy.dtype=bfloat16"
    "--policy.compile_model=false"
    "--policy.gradient_checkpointing=true"
    "--policy.push_to_hub=false"
    "--policy.chunk_size=16"
    "--use_policy_training_preset=false"
    "--optimizer.type=adamw"
    "--optimizer.lr=2e-4"
    "--optimizer.betas=[0.9,0.95]"
    "--optimizer.eps=1e-8"
    "--optimizer.weight_decay=0.01"
    "--optimizer.grad_clip_norm=1.0"
    "--scheduler.type=cosine_decay_with_warmup"
    "--scheduler.num_warmup_steps=1000"
    "--scheduler.num_decay_steps=30000"
    "--scheduler.peak_lr=2e-4"
    "--scheduler.decay_lr=2e-5"
    "--output_dir=$OUTPUT_DIR"
    "--job_name=$RUN_NAME"
    "--steps=$STEPS"
    "--batch_size=$MICRO_BATCH"
    "--num_workers=4"
    "--eval_freq=0"
    "--log_freq=1"
    "--save_checkpoint=$SAVE_CHECKPOINT"
    "--save_freq=$SAVE_FREQ"
    "--wandb.enable=false"
    "--seed=42"
)

torchrun --standalone --nproc-per-node="$NUM_PROCESSES" \
    -m lerobot.scripts.lerobot_train "${TRAIN_ARGS[@]}" >>"$LOG_FILE" 2>&1
