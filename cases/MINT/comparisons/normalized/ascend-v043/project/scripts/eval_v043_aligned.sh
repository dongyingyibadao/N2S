#!/usr/bin/env bash

set -eo pipefail

ROOT="${ASCEND_VLA_PERSISTENT_ROOT:?必须先显式设置 ASCEND_VLA_PERSISTENT_ROOT}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f /opt/ascend-vla/activate-v043.sh ]]; then
    source /opt/ascend-vla/activate-v043.sh
    VALIDATOR=/opt/ascend-vla/src/lerobot-ascend/scripts/ascend/validate_eval_artifacts.py
else
    source "$ROOT/projects/lerobot-v043-ascend/scripts/ascend/env.sh"
    VALIDATOR="$ROOT/projects/lerobot-ascend/scripts/ascend/validate_eval_artifacts.py"
fi

POLICY_KIND="${1:?policy kind is required: mint or pi05}"
CHECKPOINT="${2:?checkpoint path is required}"
OUTPUT_DIR="${3:?persistent output directory is required}"
SUITE="${4:?LIBERO suite is required}"
TASK_IDS="${5:-all}"
N_EPISODES="${6:-50}"
N_ACTION_STEPS="${7:-10}"
SEED="${8:-1000}"

OUTPUT_DIR="$(realpath -m "$OUTPUT_DIR")"
if [[ "$POLICY_KIND" != "mint" && "$POLICY_KIND" != "pi05" ]]; then
    echo "POLICY_KIND must be mint or pi05" >&2
    exit 2
fi
if [[ "$OUTPUT_DIR" != "$ROOT/"* ]]; then
    echo "Refusing non-persistent output directory: $OUTPUT_DIR" >&2
    exit 2
fi
if [[ -e "$OUTPUT_DIR" ]]; then
    echo "Refusing to overwrite existing output directory: $OUTPUT_DIR" >&2
    exit 2
fi

mkdir -p "$OUTPUT_DIR"
LOG_FILE="$OUTPUT_DIR/eval.log"
cat >"$OUTPUT_DIR/protocol.txt" <<EOF
framework=lerobot-0.4.3-ascend
libero_reset_protocol=0.6.x-sequential-init-state
eval_batch_size=1
episodes_per_task=$N_EPISODES
seed=$SEED
policy_kind=$POLICY_KIND
checkpoint=$CHECKPOINT
suite=$SUITE
task_ids=$TASK_IDS
EOF

EVAL_ARGS=(
    "--policy.path=$CHECKPOINT"
    "--policy.device=npu"
    "--policy.n_action_steps=$N_ACTION_STEPS"
    "--policy.compile_model=false"
    "--env.type=libero"
    "--env.task=$SUITE"
    "--env.max_parallel_tasks=1"
    "--eval.batch_size=1"
    "--eval.n_episodes=$N_EPISODES"
    "--output_dir=$OUTPUT_DIR"
    "--seed=$SEED"
)
if [[ "$POLICY_KIND" == "mint" ]]; then
    EVAL_ARGS+=("--discover_packages_path=lerobot_policy_mint")
fi
if [[ "$TASK_IDS" != "all" ]]; then
    EVAL_ARGS+=("--env.task_ids=$TASK_IDS")
fi

python "$SCRIPT_DIR/lerobot_eval_aligned.py" "${EVAL_ARGS[@]}" 2>&1 | tee "$LOG_FILE"

python "$VALIDATOR" \
    "$OUTPUT_DIR" 2>&1 | tee -a "$LOG_FILE"
