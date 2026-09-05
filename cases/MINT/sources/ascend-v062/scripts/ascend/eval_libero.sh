#!/usr/bin/env bash

set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

CHECKPOINT="${1:-$MINT_CHECKPOINT}"
OUTPUT_DIR="${2:-$MINT_OUTPUT_ROOT/eval/smoke_$(date +%Y%m%d_%H%M%S)}"
SUITE="${3:-libero_spatial}"
TASK_IDS="${4:-[0]}"
N_EPISODES="${5:-1}"
N_ACTION_STEPS="${6:-4}"
SEED="${7:-42}"
EPISODE_LENGTH="${8:-auto}"

OUTPUT_DIR="$(realpath -m "$OUTPUT_DIR")"
if [[ "$OUTPUT_DIR" != "$MINT_ASCEND_ROOT/"* ]]; then
    echo "Refusing non-persistent output directory: $OUTPUT_DIR" >&2
    exit 2
fi
if [[ -e "$OUTPUT_DIR" ]]; then
    echo "Refusing to overwrite existing output directory: $OUTPUT_DIR" >&2
    exit 2
fi

python "$SCRIPT_DIR/preflight_mint.py" --checkpoint "$CHECKPOINT" --require-weights
mkdir -p "$OUTPUT_DIR"
LOG_FILE="$OUTPUT_DIR/eval.log"

printf '%s\n' \
    "checkpoint=$CHECKPOINT" \
    "output_dir=$OUTPUT_DIR" \
    "suite=$SUITE" \
    "task_ids=$TASK_IDS" \
    "n_episodes=$N_EPISODES" \
    "n_action_steps=$N_ACTION_STEPS" \
    "seed=$SEED" \
    "episode_length=$EPISODE_LENGTH" | tee "$LOG_FILE"
npu-smi info 2>&1 | tee -a "$LOG_FILE"

EVAL_ARGS=(
    "--discover_packages_path=lerobot_policy_mint"
    "--policy.path=$CHECKPOINT"
    "--policy.device=npu"
    "--policy.n_action_steps=$N_ACTION_STEPS"
    "--policy.compile_model=false"
    "--env.type=libero"
    "--env.task=$SUITE"
    "--env.max_parallel_tasks=1"
    "--eval.batch_size=1"
    "--eval.n_episodes=$N_EPISODES"
    "--eval.recording=false"
    "--output_dir=$OUTPUT_DIR"
    "--seed=$SEED"
)
if [[ "$TASK_IDS" != "all" ]]; then
    EVAL_ARGS+=("--env.task_ids=$TASK_IDS")
fi
if [[ "$EPISODE_LENGTH" != "auto" ]]; then
    EVAL_ARGS+=("--env.episode_length=$EPISODE_LENGTH")
fi

lerobot-eval "${EVAL_ARGS[@]}" 2>&1 | tee -a "$LOG_FILE"
python "$MINT_ASCEND_ROOT/projects/lerobot-ascend/scripts/ascend/validate_eval_artifacts.py" \
    "$OUTPUT_DIR" 2>&1 | tee -a "$LOG_FILE"
