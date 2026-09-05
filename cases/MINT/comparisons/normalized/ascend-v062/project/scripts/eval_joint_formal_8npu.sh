#!/usr/bin/env bash

set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

PI05_CHECKPOINT="${1:-$MINT_ASCEND_ROOT/models/pi05_libero_finetuned}"
MINT_CHECKPOINT="${2:-$MINT_ASCEND_ROOT/models/mint_libero}"
RUN_TAG="${3:-joint_formal_8npu_$(date +%Y%m%d_%H%M%S)}"
CONTROL_DIR="$MINT_OUTPUT_ROOT/joint-eval/$RUN_TAG"
PI05_RUN_NAME="${RUN_TAG}_pi05_lerobot_v062"
MINT_RUN_NAME="${RUN_TAG}_mint_lerobot_v043"
PI05_SCRIPT="$MINT_ASCEND_ROOT/projects/lerobot-ascend/scripts/ascend/eval_pi05_official_4npu.sh"
MINT_SCRIPT="$MINT_ASCEND_ROOT/projects/lerobot-v043-ascend/scripts/ascend/eval_mint_official_4npu.sh"

if [[ -e "$CONTROL_DIR" ]]; then
    echo "Refusing to overwrite existing control directory: $CONTROL_DIR" >&2
    exit 2
fi
for required in "$PI05_SCRIPT" "$MINT_SCRIPT" "$PI05_CHECKPOINT" "$MINT_CHECKPOINT"; do
    if [[ ! -e "$required" ]]; then
        echo "Required path is missing: $required" >&2
        exit 2
    fi
done
NPU_COUNT="$(python -c 'import torch; print(torch.npu.device_count())')"
if (( NPU_COUNT < 8 )); then
    echo "Eight visible NPUs are required, found $NPU_COUNT" >&2
    exit 2
fi

mkdir -p "$CONTROL_DIR"
printf '%s\n' \
    "run_tag=$RUN_TAG" \
    "npu_count=$NPU_COUNT" \
    "pi05_checkpoint=$PI05_CHECKPOINT" \
    "mint_checkpoint=$MINT_CHECKPOINT" \
    "pi05_devices=0,1,2,3" \
    "mint_devices=4,5,6,7" \
    "pi05_run_name=$PI05_RUN_NAME" \
    "mint_run_name=$MINT_RUN_NAME" \
    "storage_is_shared=true" \
    "eval_batch_size=1" \
    >"$CONTROL_DIR/manifest.txt"
npu-smi info >"$CONTROL_DIR/npu_smi_before.txt" 2>&1

bash "$PI05_SCRIPT" \
    "$PI05_CHECKPOINT" "$PI05_RUN_NAME" 10 10 1000 0,1,2,3 \
    >"$CONTROL_DIR/pi05_controller.log" 2>&1 &
PI05_PID=$!
bash "$MINT_SCRIPT" \
    "$MINT_CHECKPOINT" "$MINT_RUN_NAME" 50 4 42 4,5,6,7 \
    >"$CONTROL_DIR/mint_controller.log" 2>&1 &
MINT_PID=$!
printf 'pi05_pid=%s\nmint_pid=%s\n' "$PI05_PID" "$MINT_PID" | tee "$CONTROL_DIR/processes.txt"

set +e
wait "$PI05_PID"
PI05_STATUS=$?
wait "$MINT_PID"
MINT_STATUS=$?
set -e
printf 'pi05_exit=%s\nmint_exit=%s\n' "$PI05_STATUS" "$MINT_STATUS" | tee "$CONTROL_DIR/exit_status.txt"
npu-smi info >"$CONTROL_DIR/npu_smi_after.txt" 2>&1

if (( PI05_STATUS != 0 || MINT_STATUS != 0 )); then
    echo "At least one formal evaluation controller failed" >&2
    exit 1
fi

python "$SCRIPT_DIR/generate_libero_report.py" \
    "$MINT_ASCEND_ROOT/outputs/mint-v043/eval/$MINT_RUN_NAME" \
    --primary-label "MINT Ascend (LeRobot 0.4.3 formal)" \
    --pi05-dir "$MINT_ASCEND_ROOT/outputs/eval/$PI05_RUN_NAME" \
    --output-dir "$CONTROL_DIR/report"
