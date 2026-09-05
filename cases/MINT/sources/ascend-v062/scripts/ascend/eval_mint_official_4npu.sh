#!/usr/bin/env bash

set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

CHECKPOINT="${1:-$MINT_CHECKPOINT}"
RUN_NAME="${2:-mint_current_50eps_4npu_$(date +%Y%m%d_%H%M%S)}"
EPISODES_PER_TASK="${3:-50}"
N_ACTION_STEPS="${4:-4}"
SEED="${5:-42}"
DEVICE_IDS_CSV="${6:-0,1,2,3}"
TASK_IDS="${7:-all}"
TASKS_PER_SUITE="${8:-10}"
ROOT_OUTPUT="$MINT_OUTPUT_ROOT/eval/$RUN_NAME"
SUITES=(libero_spatial libero_object libero_goal libero_10)
IFS=',' read -r -a DEVICE_IDS <<<"$DEVICE_IDS_CSV"

for value in "$EPISODES_PER_TASK" "$N_ACTION_STEPS" "$SEED" "$TASKS_PER_SUITE"; do
    if ! [[ "$value" =~ ^[0-9]+$ ]]; then
        echo "Episodes, action steps, and seed must be non-negative integers" >&2
        exit 2
    fi
done
if (( EPISODES_PER_TASK == 0 || N_ACTION_STEPS == 0 || TASKS_PER_SUITE == 0 )); then
    echo "Episodes, action steps, and tasks per suite must be positive" >&2
    exit 2
fi
if (( ${#DEVICE_IDS[@]} != ${#SUITES[@]} )); then
    echo "Exactly four comma-separated NPU device IDs are required" >&2
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
    "task_ids=$TASK_IDS" \
    "tasks_per_suite=$TASKS_PER_SUITE" \
    "suite_rollouts=$((TASKS_PER_SUITE * EPISODES_PER_TASK))" \
    "total_rollouts=$((4 * TASKS_PER_SUITE * EPISODES_PER_TASK))" \
    "eval_batch_size=1" \
    "parallelization=suite-sharded-one-suite-per-npu" \
    "n_action_steps=$N_ACTION_STEPS" \
    "seed=$SEED" \
    "device_ids=$DEVICE_IDS_CSV" \
    "suites=${SUITES[*]}" \
    >"$ROOT_OUTPUT/benchmark_manifest.txt"

PIDS=()
for index in "${!SUITES[@]}"; do
    suite="${SUITES[$index]}"
    device="${DEVICE_IDS[$index]}"
    ASCEND_RT_VISIBLE_DEVICES="$device" "$SCRIPT_DIR/eval_libero.sh" \
        "$CHECKPOINT" \
        "$ROOT_OUTPUT/$suite" \
        "$suite" \
        "$TASK_IDS" \
        "$EPISODES_PER_TASK" \
        "$N_ACTION_STEPS" \
        "$SEED" \
        >"$ROOT_OUTPUT/${suite}_lane.log" 2>&1 &
    PIDS+=("$!")
    printf 'npu=%s suite=%s pid=%s\n' "$device" "$suite" "$!" | tee -a "$ROOT_OUTPUT/processes.txt"
done

FAILED=0
for index in "${!PIDS[@]}"; do
    set +e
    wait "${PIDS[$index]}"
    status=$?
    set -e
    printf 'npu=%s suite=%s exit=%s\n' \
        "${DEVICE_IDS[$index]}" "${SUITES[$index]}" "$status" | tee -a "$ROOT_OUTPUT/exit_status.txt"
    if (( status != 0 )); then
        FAILED=1
    fi
done
if (( FAILED != 0 )); then
    echo "At least one MINT current-framework evaluation lane failed" >&2
    exit 1
fi

python "$SCRIPT_DIR/generate_libero_report.py" \
    "$ROOT_OUTPUT" \
    --primary-label "MINT Ascend (LeRobot 0.6.2 formal)"
