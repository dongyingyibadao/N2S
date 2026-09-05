#!/usr/bin/env bash
set -euo pipefail

CASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="${N2S_OUTPUT_DIR:-$CASE_DIR/evidence/cuda-blocks}"
PYTHON="${N2S_PYTHON:-python3}"

mkdir -p "$OUTPUT_DIR"
export PYTHONDONTWRITEBYTECODE=1
export TORCH_DEVICE_BACKEND_AUTOLOAD=0
FAILURES=0

run_logged() {
    local log="$1"
    shift
    if "$@" >"$log" 2>&1; then
        return 0
    else
        local status=$?
        printf 'command failed with status %d: ' "$status" >>"$log"
        printf '%q ' "$@" >>"$log"
        printf '\n' >>"$log"
        FAILURES=$((FAILURES + 1))
    fi
}

run_logged "$OUTPUT_DIR/candidate_checks.log" \
    "$PYTHON" "$CASE_DIR/tests/candidate_checks.py" \
    --backend cuda --output "$OUTPUT_DIR/candidate_checks.json"

run_logged "$OUTPUT_DIR/cache_dtype_operator_ab.log" \
    "$PYTHON" "$CASE_DIR/tests/cache_dtype_ab.py" \
    --backend cuda --output "$OUTPUT_DIR/cache_dtype_operator_ab.json"

run_logged "$OUTPUT_DIR/runtime_rule_ab.log" \
    "$PYTHON" "$CASE_DIR/tests/runtime_rule_ab.py" \
    --backend cuda --output "$OUTPUT_DIR/runtime_rule_ab.json"

echo "CUDA block A/B evidence written to $OUTPUT_DIR; harness failures: $FAILURES"
exit "$((FAILURES > 0))"
