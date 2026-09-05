#!/usr/bin/env bash

set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

SESSION_DIR="${1:?Usage: $0 SESSION_DIR MINT_PID PI05_PID}"
MINT_PID="${2:?Usage: $0 SESSION_DIR MINT_PID PI05_PID}"
PI05_PID="${3:?Usage: $0 SESSION_DIR MINT_PID PI05_PID}"
INTERVAL_SECONDS="${TELEMETRY_INTERVAL_SECONDS:-60}"
LOG_FILE="$SESSION_DIR/telemetry.log"

if [[ "$SESSION_DIR" != "$MINT_ASCEND_ROOT/"* || ! -d "$SESSION_DIR" ]]; then
    echo "Invalid persistent session directory: $SESSION_DIR" >&2
    exit 2
fi
if ! [[ "$INTERVAL_SECONDS" =~ ^[1-9][0-9]*$ ]]; then
    echo "TELEMETRY_INTERVAL_SECONDS must be a positive integer" >&2
    exit 2
fi

while kill -0 "$MINT_PID" 2>/dev/null || kill -0 "$PI05_PID" 2>/dev/null; do
    {
        printf '\n===== %s =====\n' "$(date --iso-8601=seconds)"
        ps -p "$MINT_PID,$PI05_PID" -o pid,ppid,stat,etime,%cpu,%mem,rss,cmd || true
        npu-smi info || true
    } >>"$LOG_FILE" 2>&1
    sleep "$INTERVAL_SECONDS"
done

printf '\n===== %s training processes exited =====\n' "$(date --iso-8601=seconds)" >>"$LOG_FILE"
