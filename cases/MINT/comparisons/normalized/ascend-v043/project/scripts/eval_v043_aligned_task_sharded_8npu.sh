#!/usr/bin/env bash

set -eo pipefail

ROOT="${ASCEND_VLA_PERSISTENT_ROOT:?必须先显式设置 ASCEND_VLA_PERSISTENT_ROOT}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f /opt/ascend-vla/src/MINT/scripts/ascend/generate_libero_report.py ]]; then
    REPORT_SCRIPT=/opt/ascend-vla/src/MINT/scripts/ascend/generate_libero_report.py
else
    REPORT_SCRIPT="$ROOT/projects/MINT/scripts/ascend/generate_libero_report.py"
fi

POLICY_KIND="${1:?policy kind is required: mint or pi05}"
CHECKPOINT="${2:?checkpoint path is required}"
RUN_NAME="${3:?run name is required}"
N_EPISODES="${4:-50}"
N_ACTION_STEPS="${5:-10}"
SEED="${6:-1000}"
DEVICE_IDS_CSV="${7:-0,1,2,3,4,5,6,7}"

OUTPUT_ROOT="$ROOT/outputs/eval-v043-aligned/$RUN_NAME"
if [[ -e "$OUTPUT_ROOT" ]]; then
    echo "Refusing to overwrite existing output: $OUTPUT_ROOT" >&2
    exit 2
fi
mkdir -p "$OUTPUT_ROOT"

IFS=',' read -r -a device_ids <<<"$DEVICE_IDS_CSV"
if [[ "${#device_ids[@]}" -ne 8 ]]; then
    echo "Exactly 8 device IDs are required" >&2
    exit 2
fi

suites=(libero_10 libero_spatial libero_object libero_goal)
task_ranges=("[0,1,2,3,4]" "[5,6,7,8,9]")
pids=()
lane=0

for suite in "${suites[@]}"; do
    for task_ids in "${task_ranges[@]}"; do
        shard_name="tasks0_4"
        if [[ "$task_ids" == "[5,6,7,8,9]" ]]; then
            shard_name="tasks5_9"
        fi
        lane_output="$OUTPUT_ROOT/$shard_name/$suite"
        lane_log="$OUTPUT_ROOT/${suite}_${shard_name}_lane.log"
        ASCEND_RT_VISIBLE_DEVICES="${device_ids[$lane]}" \
            "$SCRIPT_DIR/eval_v043_aligned.sh" \
            "$POLICY_KIND" "$CHECKPOINT" "$lane_output" "$suite" "$task_ids" \
            "$N_EPISODES" "$N_ACTION_STEPS" "$SEED" >"$lane_log" 2>&1 &
        pids+=("$!")
        lane=$((lane + 1))
    done
done

status=0
for pid in "${pids[@]}"; do
    if ! wait "$pid"; then
        status=1
    fi
done

if (( status != 0 )); then
    echo "At least one aligned evaluation lane failed; inspect $OUTPUT_ROOT/*_lane.log" >&2
    exit "$status"
fi

printf '%s\n' \
    "framework=lerobot-0.4.3-ascend" \
    "libero_reset_protocol=0.6.x-sequential-init-state" \
    "policy_kind=$POLICY_KIND" \
    "checkpoint=$CHECKPOINT" \
    "episodes_per_task=$N_EPISODES" \
    "total_episodes=$((4 * 10 * N_EPISODES))" \
    "device_ids=$DEVICE_IDS_CSV" >"$OUTPUT_ROOT/campaign.txt"

MINT_ASCEND_ROOT="$ROOT" python \
    "$REPORT_SCRIPT" \
    "$OUTPUT_ROOT" \
    --primary-label="$POLICY_KIND LeRobot 0.4.3 aligned-init-state"

echo "Aligned evaluation completed: $OUTPUT_ROOT"
