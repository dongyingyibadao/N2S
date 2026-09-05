#!/usr/bin/env bash
set -euo pipefail

CASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="${N2S_OUTPUT_DIR:-$CASE_DIR/evidence/cuda}"
PYTHON="${N2S_PYTHON:-python3}"

mkdir -p "$OUTPUT_DIR"
export PYTHONDONTWRITEBYTECODE=1
# The capture host has torch-npu registered as an auto-loaded backend. CUDA-only
# checks must not require CANN libraries; an NVIDIA host has no need to auto-load it.
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

MODEL_RULES=()
if [[ "${N2S_RUN_MODEL_AB:-0}" == "1" ]]; then
    MODEL_RULES=(cache-dtype compile sinusoidal-fp64)
elif [[ "${N2S_RUN_CACHE_DTYPE_MODEL_AB:-0}" == "1" ]]; then
    MODEL_RULES=(cache-dtype)
fi

if [[ "${#MODEL_RULES[@]}" -gt 0 ]]; then
    MODEL_SOURCE="$CASE_DIR/sources/ascend-v062/lerobot_policy_mint/src"
    MODEL_CHECKPOINT_ARGS=()
    if [[ -n "${N2S_MINT_CHECKPOINT:-}" ]]; then
        MODEL_CHECKPOINT_ARGS=(--checkpoint "$N2S_MINT_CHECKPOINT")
    fi
    for rule in "${MODEL_RULES[@]}"; do
        case "$rule" in
            cache-dtype) prefix="cache_dtype" ;;
            compile) prefix="compile" ;;
            sinusoidal-fp64) prefix="sinusoidal_fp64" ;;
        esac
        run_logged "$OUTPUT_DIR/${prefix}_model_inference_ab.log" \
            "$PYTHON" "$CASE_DIR/tests/cache_dtype_model_ab.py" \
            --backend cuda --rule "$rule" --source-root "$MODEL_SOURCE" \
            "${MODEL_CHECKPOINT_ARGS[@]}" \
            --output "$OUTPUT_DIR/${prefix}_model_inference_ab.json"
        if [[ "${N2S_RUN_MODEL_TRAINING_AB:-${N2S_RUN_CACHE_DTYPE_TRAINING_AB:-0}}" == "1" ]]; then
            run_logged "$OUTPUT_DIR/${prefix}_model_training_ab.log" \
                "$PYTHON" "$CASE_DIR/tests/cache_dtype_model_ab.py" \
                --backend cuda --rule "$rule" --mode training --source-root "$MODEL_SOURCE" \
                "${MODEL_CHECKPOINT_ARGS[@]}" \
                --output "$OUTPUT_DIR/${prefix}_model_training_ab.json"
        fi
    done
fi

echo "CUDA exploratory evidence written to $OUTPUT_DIR; harness failures: $FAILURES"
exit "$((FAILURES > 0))"
