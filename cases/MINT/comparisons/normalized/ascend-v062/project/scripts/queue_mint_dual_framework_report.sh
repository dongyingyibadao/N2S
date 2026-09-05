#!/usr/bin/env bash

set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"
set -u

CURRENT_DIR="${1:?Usage: $0 CURRENT_DIR V043_DIR OUTPUT_DIR [TIMEOUT_SECONDS]}"
V043_DIR="${2:?Usage: $0 CURRENT_DIR V043_DIR OUTPUT_DIR [TIMEOUT_SECONDS]}"
OUTPUT_DIR="${3:?Usage: $0 CURRENT_DIR V043_DIR OUTPUT_DIR [TIMEOUT_SECONDS]}"
TIMEOUT_SECONDS="${4:-172800}"
POLL_SECONDS="${MINT_REPORT_POLL_SECONDS:-60}"

for variable in CURRENT_DIR V043_DIR OUTPUT_DIR; do
    value="$(realpath -m "${!variable}")"
    if [[ "$value" != "$MINT_ASCEND_ROOT/"* ]]; then
        echo "$variable is outside the persistent root: $value" >&2
        exit 2
    fi
    printf -v "$variable" '%s' "$value"
done
for value in "$TIMEOUT_SECONDS" "$POLL_SECONDS"; do
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
LOG_FILE="$OUTPUT_DIR/controller.log"
exec > >(tee -a "$LOG_FILE") 2>&1

printf '%s\n' \
    "current_dir=$CURRENT_DIR" \
    "v043_dir=$V043_DIR" \
    "expected_eval_files_per_framework=4" \
    "expected_rollouts_per_framework=2000" \
    "timeout_seconds=$TIMEOUT_SECONDS" \
    "started_at=$(date --iso-8601=seconds)"

eval_file_count() {
    if [[ ! -d "$1" ]]; then
        echo 0
        return
    fi
    find "$1" -type f -name eval_info.json | wc -l
}

deadline=$((SECONDS + TIMEOUT_SECONDS))
while true; do
    current_count="$(eval_file_count "$CURRENT_DIR")"
    v043_count="$(eval_file_count "$V043_DIR")"
    printf '%s current=%s/4 v043=%s/4\n' \
        "$(date --iso-8601=seconds)" "$current_count" "$v043_count"
    if [[ "$current_count" == 4 && "$v043_count" == 4 ]]; then
        break
    fi
    if (( SECONDS >= deadline )); then
        echo "Timed out waiting for MINT evaluation artifacts" >&2
        exit 1
    fi
    sleep "$POLL_SECONDS"
done

python "$SCRIPT_DIR/generate_libero_report.py" \
    "$CURRENT_DIR" \
    --output-dir "$OUTPUT_DIR/report" \
    --primary-label "MINT 60K Ascend (LeRobot 0.6.2)" \
    --mint-v043-dir "$V043_DIR"

python - "$OUTPUT_DIR/report/report.json" <<'PY'
import json
import sys

report = json.load(open(sys.argv[1], encoding="utf-8"))
if report["trials"] != 2000:
    raise RuntimeError(f"Current-framework trials={report['trials']}, expected 2000")
for row in report["per_suite"]:
    if row["trials"] != 500 or row["mint_v043_trials"] != 500:
        raise RuntimeError(
            f"{row['suite']} trials={row['trials']}, "
            f"v043_trials={row['mint_v043_trials']}; expected 500 each"
        )
PY

printf 'status=complete\ncompleted_at=%s\nreport=%s\n' \
    "$(date --iso-8601=seconds)" "$OUTPUT_DIR/report/report.json" \
    | tee "$OUTPUT_DIR/status.txt"
