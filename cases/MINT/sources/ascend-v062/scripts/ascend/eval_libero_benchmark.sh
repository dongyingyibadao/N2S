#!/usr/bin/env bash

set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

CHECKPOINT="${1:-$MINT_CHECKPOINT}"
EPISODES_PER_TASK="${2:-50}"
RUN_NAME="${3:-mint_libero_benchmark_$(date +%Y%m%d_%H%M%S)}"
N_ACTION_STEPS="${4:-4}"
SEED="${5:-42}"
ROOT_OUTPUT="$MINT_OUTPUT_ROOT/eval/$RUN_NAME"

if [[ -e "$ROOT_OUTPUT" ]]; then
    echo "Refusing to overwrite existing output directory: $ROOT_OUTPUT" >&2
    exit 2
fi
mkdir -p "$ROOT_OUTPUT"
printf '%s\n' \
    "protocol_id=mint-paper-alignment-50eps-per-task" \
    "comparison_target=MINT-4B_97.4_99.6_98.2_97.8" \
    "framework=lerobot-current-ascend" \
    "checkpoint=$CHECKPOINT" \
    "episodes_per_task=$EPISODES_PER_TASK" \
    "tasks_per_suite=10" \
    "suite_rollouts=$((10 * EPISODES_PER_TASK))" \
    "total_rollouts=$((40 * EPISODES_PER_TASK))" \
    "n_action_steps=$N_ACTION_STEPS" \
    "seed=$SEED" \
    "suites=libero_spatial,libero_object,libero_goal,libero_10" \
    >"$ROOT_OUTPUT/benchmark_manifest.txt"

for suite in libero_spatial libero_object libero_goal libero_10; do
    "$SCRIPT_DIR/eval_libero.sh" \
        "$CHECKPOINT" \
        "$ROOT_OUTPUT/${suite}" \
        "$suite" \
        all \
        "$EPISODES_PER_TASK" \
        "$N_ACTION_STEPS" \
        "$SEED"
done

python "$SCRIPT_DIR/generate_libero_report.py" "$ROOT_OUTPUT"
