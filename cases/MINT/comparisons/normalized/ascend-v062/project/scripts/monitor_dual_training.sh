#!/usr/bin/env bash

set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

SESSION_DIR="${1:?Usage: $0 SESSION_DIR}"
if [[ "$SESSION_DIR" != "$MINT_ASCEND_ROOT/"* || ! -d "$SESSION_DIR" ]]; then
    echo "Invalid persistent session directory: $SESSION_DIR" >&2
    exit 2
fi

for name in mint pi05; do
    pid_file="$SESSION_DIR/$name.pid"
    if [[ ! -f "$pid_file" ]]; then
        echo "$name: missing pid file"
        continue
    fi
    pid="$(<"$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then
        echo "$name: running pid=$pid"
    else
        echo "$name: stopped pid=$pid"
    fi
    echo "$name recent log:"
    tail -n 20 "$SESSION_DIR/${name}_launcher.log" 2>/dev/null || true
    echo "$name error scan:"
    if command -v rg >/dev/null 2>&1; then
        rg -i "out of memory|oom|traceback|runtimeerror|hccl.*error|acl.*error" \
            "$SESSION_DIR/${name}_launcher.log" 2>/dev/null \
            | rg -vi "libtorchcodec loading traceback" | tail -n 10 || true
    else
        grep -Ei "out of memory|oom|traceback|runtimeerror|hccl.*error|acl.*error" \
            "$SESSION_DIR/${name}_launcher.log" 2>/dev/null \
            | grep -Eiv "libtorchcodec loading traceback" | tail -n 10 || true
    fi
done

echo "telemetry recent log:"
tail -n 80 "$SESSION_DIR/telemetry.log" 2>/dev/null || true
echo "telemetry launcher errors:"
tail -n 20 "$SESSION_DIR/telemetry_launcher.log" 2>/dev/null || true

npu-smi info
find "$LEROBOT_OUTPUT_ROOT/train" "$MINT_OUTPUT_ROOT/train" \
    -path "*/checkpoints/*/pretrained_model/model.safetensors" \
    -printf '%T@ %s %p\n' 2>/dev/null | sort -nr | head -n 10
