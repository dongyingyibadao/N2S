#!/usr/bin/env bash

set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

NUM_PROCESSES="${1:-4}"
MICRO_BATCH="${2:-8}"
RUN_NAME="${3:-mint_libero_npu_reproduction_$(date +%Y%m%d_%H%M%S)}"
OPTIMIZER_UPDATES="${4:-30000}"
SAVE_EVERY_UPDATES="${5:-2000}"
SAVE_CHECKPOINT="${6:-true}"
TARGET_GLOBAL_BATCH=128
DATASET="$HF_LEROBOT_HOME/lerobot/libero"
OUTPUT_DIR="$MINT_OUTPUT_ROOT/train/$RUN_NAME"

for value in "$NUM_PROCESSES" "$MICRO_BATCH" "$OPTIMIZER_UPDATES" "$SAVE_EVERY_UPDATES"; do
    if ! [[ "$value" =~ ^[1-9][0-9]*$ ]]; then
        echo "NUM_PROCESSES, MICRO_BATCH, and OPTIMIZER_UPDATES must be positive integers" >&2
        exit 2
    fi
done
if [[ "$SAVE_CHECKPOINT" != "true" && "$SAVE_CHECKPOINT" != "false" ]]; then
    echo "SAVE_CHECKPOINT must be true or false" >&2
    exit 2
fi

SAMPLES_PER_MICRO_STEP=$((NUM_PROCESSES * MICRO_BATCH))
if (( TARGET_GLOBAL_BATCH % SAMPLES_PER_MICRO_STEP != 0 )); then
    echo "128 must be divisible by NUM_PROCESSES * MICRO_BATCH" >&2
    exit 2
fi
GRAD_ACCUM=$((TARGET_GLOBAL_BATCH / SAMPLES_PER_MICRO_STEP))
MICRO_STEPS=$((OPTIMIZER_UPDATES * GRAD_ACCUM))
WARMUP_STEPS=$((1000 * GRAD_ACCUM))
DECAY_STEPS=$((30000 * GRAD_ACCUM))
SAVE_FREQ=$((SAVE_EVERY_UPDATES * GRAD_ACCUM))

if [[ -e "$OUTPUT_DIR" ]]; then
    echo "Refusing to overwrite existing run directory: $OUTPUT_DIR" >&2
    exit 2
fi
python "$SCRIPT_DIR/preflight_mint.py" \
    --tokenizer "$MINT_TOKENIZER" \
    --dataset "$DATASET" \
    --require-complete-dataset
if [[ ! -f "$MINT_PI05_BASE/model.safetensors" ]]; then
    echo "PI0.5 base checkpoint is incomplete: $MINT_PI05_BASE" >&2
    exit 2
fi

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
    "initialization=$MINT_PI05_BASE" \
    "tokenizer=$MINT_TOKENIZER/ms_vqvae.pth" \
    "dataset=$DATASET" \
    "output_dir=$OUTPUT_DIR" \
    "num_processes=$NUM_PROCESSES" \
    "micro_batch_per_process=$MICRO_BATCH" \
    "gradient_accumulation_steps=$GRAD_ACCUM" \
    "effective_global_batch=$TARGET_GLOBAL_BATCH" \
    "official_recipe_source=arXiv:2602.08602v3 Appendix Table VI and LIBERO implementation details" \
    "official_hardware=4xNVIDIA_H200" \
    "official_learning_rate=2e-4" \
    "official_optimizer=AdamW_betas_0.9_0.95_weight_decay_0.01" \
    "official_training_iterations=30000" \
    "official_dataset=joint_4_suite_LIBERO_273465_frames" \
    "initialization_scope=pi05_PaliGemma_backbone_only" \
    "action_expert_initialization=random_as_specified_by_paper" \
    "optimizer_updates=$OPTIMIZER_UPDATES" \
    "save_every_optimizer_updates=$SAVE_EVERY_UPDATES" \
    "save_checkpoint=$SAVE_CHECKPOINT" \
    "trainer_micro_steps=$MICRO_STEPS" \
    "scheduler_steps_per_optimizer_update=$GRAD_ACCUM" \
    "scheduler_warmup_optimizer_updates=1000" \
    "scheduler_decay_optimizer_updates=30000" \
    "scheduler_warmup_steps=$WARMUP_STEPS" \
    "scheduler_decay_steps=$DECAY_STEPS" | tee "$LOG_FILE"
npu-smi info 2>&1 | tee -a "$LOG_FILE"

TRAIN_ARGS=(
    "--discover_packages_path=lerobot_policy_mint"
    "--dataset.repo_id=lerobot/libero"
    "--dataset.root=$DATASET"
    "--dataset.episodes=null"
    "--dataset.revision=a1aaacb7f6cd6ee5fb43120f673cebb0cfea7dd4"
    "--dataset.video_backend=pyav"
    "--dataset.return_uint8=true"
    "--policy.type=mint"
    "--policy.pretrained_path=$MINT_PI05_BASE"
    "--policy.vqvae_name_or_path=$MINT_TOKENIZER/ms_vqvae.pth"
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
    "--scheduler.num_warmup_steps=$WARMUP_STEPS"
    "--scheduler.num_decay_steps=$DECAY_STEPS"
    "--scheduler.peak_lr=2e-4"
    "--scheduler.decay_lr=2e-5"
    "--accelerator.gradient_accumulation.steps=$GRAD_ACCUM"
    "--output_dir=$OUTPUT_DIR"
    "--job_name=$RUN_NAME"
    "--steps=$MICRO_STEPS"
    "--batch_size=$MICRO_BATCH"
    "--num_workers=4"
    "--env_eval_freq=0"
    "--eval_steps=0"
    "--log_freq=$GRAD_ACCUM"
    "--save_checkpoint=$SAVE_CHECKPOINT"
    "--save_freq=$SAVE_FREQ"
    "--ema.enable=false"
    "--wandb.enable=false"
    "--seed=42"
)

torchrun --standalone --nproc-per-node="$NUM_PROCESSES" "$(command -v lerobot-train)" \
    "${TRAIN_ARGS[@]}" 2>&1 | tee -a "$LOG_FILE"
