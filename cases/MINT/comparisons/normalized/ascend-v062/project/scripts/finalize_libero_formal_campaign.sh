#!/usr/bin/env bash

set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

MINT_CURRENT_DIR="${1:?Usage: $0 MINT_CURRENT_DIR MINT_V043_DIR PI05_CURRENT_DIR PI05_V043_DIR OUTPUT_DIR [TIMEOUT_SECONDS]}"
MINT_V043_DIR="${2:?Usage: $0 MINT_CURRENT_DIR MINT_V043_DIR PI05_CURRENT_DIR PI05_V043_DIR OUTPUT_DIR [TIMEOUT_SECONDS]}"
PI05_CURRENT_DIR="${3:?Usage: $0 MINT_CURRENT_DIR MINT_V043_DIR PI05_CURRENT_DIR PI05_V043_DIR OUTPUT_DIR [TIMEOUT_SECONDS]}"
PI05_V043_DIR="${4:?Usage: $0 MINT_CURRENT_DIR MINT_V043_DIR PI05_CURRENT_DIR PI05_V043_DIR OUTPUT_DIR [TIMEOUT_SECONDS]}"
OUTPUT_DIR="${5:?Usage: $0 MINT_CURRENT_DIR MINT_V043_DIR PI05_CURRENT_DIR PI05_V043_DIR OUTPUT_DIR [TIMEOUT_SECONDS]}"
TIMEOUT_SECONDS="${6:-129600}"
POLL_SECONDS="${FORMAL_REPORT_POLL_SECONDS:-60}"
MINT_CURRENT_EXPECTED_FILES="${MINT_CURRENT_EXPECTED_FILES:-4}"
MINT_V043_EXPECTED_FILES="${MINT_V043_EXPECTED_FILES:-8}"
PI05_CURRENT_EXPECTED_FILES="${PI05_CURRENT_EXPECTED_FILES:-4}"
PI05_V043_EXPECTED_FILES="${PI05_V043_EXPECTED_FILES:-4}"

for variable in MINT_CURRENT_DIR MINT_V043_DIR PI05_CURRENT_DIR PI05_V043_DIR OUTPUT_DIR; do
    value="$(realpath -m "${!variable}")"
    if [[ "$value" != "$MINT_ASCEND_ROOT/"* ]]; then
        echo "$variable is outside the persistent root: $value" >&2
        exit 2
    fi
    printf -v "$variable" '%s' "$value"
done
for value in \
    "$TIMEOUT_SECONDS" \
    "$POLL_SECONDS" \
    "$MINT_CURRENT_EXPECTED_FILES" \
    "$MINT_V043_EXPECTED_FILES" \
    "$PI05_CURRENT_EXPECTED_FILES" \
    "$PI05_V043_EXPECTED_FILES"; do
    if ! [[ "$value" =~ ^[1-9][0-9]*$ ]]; then
        echo "Timeout and polling interval must be positive integers" >&2
        exit 2
    fi
done
if [[ -e "$OUTPUT_DIR" ]]; then
    echo "Refusing to overwrite existing output directory: $OUTPUT_DIR" >&2
    exit 2
fi

mkdir -p "$OUTPUT_DIR"
PROGRESS_LOG="$OUTPUT_DIR/finalizer.log"
printf '%s\n' \
    "mint_current_dir=$MINT_CURRENT_DIR" \
    "mint_v043_dir=$MINT_V043_DIR" \
    "pi05_current_dir=$PI05_CURRENT_DIR" \
    "pi05_v043_dir=$PI05_V043_DIR" \
    "expected_eval_files=$MINT_CURRENT_EXPECTED_FILES,$MINT_V043_EXPECTED_FILES,$PI05_CURRENT_EXPECTED_FILES,$PI05_V043_EXPECTED_FILES" \
    "expected_rollouts_per_model=2000" \
    "expected_rollouts_per_suite=500" \
    "timeout_seconds=$TIMEOUT_SECONDS" \
    "poll_seconds=$POLL_SECONDS" \
    "started_at=$(date --iso-8601=seconds)" \
    >"$OUTPUT_DIR/finalizer_manifest.txt"

eval_file_count() {
    if [[ ! -d "$1" ]]; then
        echo 0
        return
    fi
    find "$1" -type f -name eval_info.json 2>/dev/null | wc -l
}

deadline=$((SECONDS + TIMEOUT_SECONDS))
while true; do
    mint_current_count="$(eval_file_count "$MINT_CURRENT_DIR")"
    mint_v043_count="$(eval_file_count "$MINT_V043_DIR")"
    pi05_current_count="$(eval_file_count "$PI05_CURRENT_DIR")"
    pi05_v043_count="$(eval_file_count "$PI05_V043_DIR")"
    printf '%s mint_current=%s/%s mint_v043=%s/%s pi05_current=%s/%s pi05_v043=%s/%s\n' \
        "$(date --iso-8601=seconds)" \
        "$mint_current_count" "$MINT_CURRENT_EXPECTED_FILES" \
        "$mint_v043_count" "$MINT_V043_EXPECTED_FILES" \
        "$pi05_current_count" "$PI05_CURRENT_EXPECTED_FILES" \
        "$pi05_v043_count" "$PI05_V043_EXPECTED_FILES" \
        >>"$PROGRESS_LOG"
    if (( mint_current_count == MINT_CURRENT_EXPECTED_FILES \
        && mint_v043_count == MINT_V043_EXPECTED_FILES \
        && pi05_current_count == PI05_CURRENT_EXPECTED_FILES \
        && pi05_v043_count == PI05_V043_EXPECTED_FILES )); then
        break
    fi
    if (( SECONDS >= deadline )); then
        echo "Timed out waiting for all formal evaluation artifacts" | tee -a "$PROGRESS_LOG" >&2
        exit 1
    fi
    sleep "$POLL_SECONDS"
done

python "$SCRIPT_DIR/generate_libero_report.py" \
    "$MINT_CURRENT_DIR" \
    --output-dir "$OUTPUT_DIR/report" \
    --primary-label "MINT Ascend (LeRobot 0.6.2, 50 episodes/task)" \
    --mint-v043-dir "$MINT_V043_DIR" \
    --pi05-dir "$PI05_CURRENT_DIR" \
    --pi05-v043-dir "$PI05_V043_DIR" \
    >"$OUTPUT_DIR/report_generator.log" 2>&1

python - "$OUTPUT_DIR/report/report.json" <<'PY'
import json
import sys

report = json.load(open(sys.argv[1], encoding="utf-8"))
if report["trials"] != 2000:
    raise RuntimeError(f"Primary MINT trial count is {report['trials']}, expected 2000")
for row in report["per_suite"]:
    for field in ("trials", "mint_v043_trials", "pi05_npu_trials", "pi05_v043_trials"):
        if row[field] != 500:
            raise RuntimeError(
                f"{row['suite']} {field} is {row[field]}, expected 500"
            )
PY

printf '%s\n' \
    "status=passed" \
    "completed_at=$(date --iso-8601=seconds)" \
    "report=$OUTPUT_DIR/report/report.json" \
    >"$OUTPUT_DIR/result.txt"
