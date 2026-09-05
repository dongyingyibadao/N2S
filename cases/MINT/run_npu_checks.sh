#!/usr/bin/env bash
set -euo pipefail

CASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "$CASE_DIR/../../.." && pwd)"
OUTPUT_DIR="${N2S_OUTPUT_DIR:-$CASE_DIR/evidence/npu}"
PYTHON="${N2S_PYTHON:-/opt/ascend-vla/envs/lerobot-npu/bin/python}"
PERSISTENT_ROOT="${ASCEND_VLA_PERSISTENT_ROOT:-$WORKSPACE_ROOT/workspace}"

mkdir -p "$OUTPUT_DIR"
set +u
source /usr/local/Ascend/cann-8.5.0/set_env.sh
set -u
export ASCEND_RT_VISIBLE_DEVICES="${ASCEND_RT_VISIBLE_DEVICES:-0}"
export PYTHONDONTWRITEBYTECODE=1

"$PYTHON" "$CASE_DIR/tests/candidate_checks.py" \
    --backend npu --output "$OUTPUT_DIR/candidate_checks.json" \
    >"$OUTPUT_DIR/candidate_checks.log" 2>&1

"$PYTHON" "$CASE_DIR/tests/cache_dtype_ab.py" \
    --backend npu --output "$OUTPUT_DIR/cache_dtype_operator_ab.json" \
    >"$OUTPUT_DIR/cache_dtype_operator_ab.log" 2>&1

"$PYTHON" "$CASE_DIR/tests/runtime_rule_ab.py" \
    --backend npu --output "$OUTPUT_DIR/runtime_rule_ab.json" \
    >"$OUTPUT_DIR/runtime_rule_ab.log" 2>&1

"$PYTHON" "$CASE_DIR/tests/run_snapshot_ops.py" \
    "$CASE_DIR/sources/ascend-v062/scripts/ascend/smoke_mint_ops.py" --seed 42 \
    >"$OUTPUT_DIR/snapshot_ops_smoke.json" 2>"$OUTPUT_DIR/snapshot_ops_smoke.stderr.log"

(
    export ASCEND_VLA_PERSISTENT_ROOT="$PERSISTENT_ROOT"
    source /opt/ascend-vla/activate-v062.sh >/dev/null
    SNAPSHOT_SRC="$CASE_DIR/sources/ascend-v062/lerobot_policy_mint/src"
    export PYTHONPATH="$SNAPSHOT_SRC:$PYTHONPATH"
    "$PYTHON" "$CASE_DIR/tests/snapshot_import_check.py" \
        --expected-source "$SNAPSHOT_SRC" --output "$OUTPUT_DIR/snapshot_import_v062.json"
) >"$OUTPUT_DIR/snapshot_import_v062.log" 2>&1

(
    export ASCEND_VLA_PERSISTENT_ROOT="$PERSISTENT_ROOT"
    source /opt/ascend-vla/activate-v043.sh >/dev/null
    SNAPSHOT_SRC="$CASE_DIR/sources/ascend-v043/lerobot_policy_mint/src"
    export PYTHONPATH="$SNAPSHOT_SRC:$PYTHONPATH"
    "$PYTHON" "$CASE_DIR/tests/snapshot_import_check.py" \
        --expected-source "$SNAPSHOT_SRC" --output "$OUTPUT_DIR/snapshot_import_v043.json"
) >"$OUTPUT_DIR/snapshot_import_v043.log" 2>&1

"$PYTHON" "$CASE_DIR/tests/tool_checks.py" --output "$OUTPUT_DIR/tool_checks.json" \
    >"$OUTPUT_DIR/tool_checks.log" 2>&1

if [[ "${N2S_RUN_MODEL_SMOKES:-0}" == "1" ]]; then
    export ASCEND_VLA_PERSISTENT_ROOT="$PERSISTENT_ROOT"
    source /opt/ascend-vla/activate-v062.sh >/dev/null
    SNAPSHOT_SRC="$CASE_DIR/sources/ascend-v062/lerobot_policy_mint/src"
    export PYTHONPATH="$SNAPSHOT_SRC:$PYTHONPATH"
    MODEL_SMOKE="$CASE_DIR/sources/ascend-v062/scripts/ascend/smoke_mint_model.py"
    "$PYTHON" "$MODEL_SMOKE" --mode inference --warmup 0 --repeats 1 \
        --output-json "$OUTPUT_DIR/random_weight_inference.json" \
        >"$OUTPUT_DIR/random_weight_inference.log" 2>&1
    "$PYTHON" "$MODEL_SMOKE" --mode training --optimizer-step \
        --output-json "$OUTPUT_DIR/random_weight_training.json" \
        >"$OUTPUT_DIR/random_weight_training.log" 2>&1
    if [[ -f "$PERSISTENT_ROOT/models/mint_libero/model.safetensors" ]]; then
        "$PYTHON" "$MODEL_SMOKE" --mode inference --warmup 0 --repeats 1 \
            --checkpoint "$PERSISTENT_ROOT/models/mint_libero" \
            --output-json "$OUTPUT_DIR/checkpoint_inference.json" \
            >"$OUTPUT_DIR/checkpoint_inference.log" 2>&1
    else
        printf '{"status":"skipped","reason":"local checkpoint not found","path":"%s"}\n' \
            "$PERSISTENT_ROOT/models/mint_libero" >"$OUTPUT_DIR/checkpoint_inference.json"
    fi
fi

MODEL_RULES=()
if [[ "${N2S_RUN_MODEL_AB:-0}" == "1" ]]; then
    MODEL_RULES=(cache-dtype compile sinusoidal-fp64)
elif [[ "${N2S_RUN_CACHE_DTYPE_MODEL_AB:-0}" == "1" ]]; then
    MODEL_RULES=(cache-dtype)
fi

if [[ "${#MODEL_RULES[@]}" -gt 0 ]]; then
    export ASCEND_VLA_PERSISTENT_ROOT="$PERSISTENT_ROOT"
    source /opt/ascend-vla/activate-v062.sh >/dev/null
    MODEL_SOURCE="$CASE_DIR/sources/ascend-v062/lerobot_policy_mint/src"
    MODEL_CHECKPOINT_ARGS=()
    if [[ -f "$PERSISTENT_ROOT/models/mint_libero/model.safetensors" ]]; then
        MODEL_CHECKPOINT_ARGS=(--checkpoint "$PERSISTENT_ROOT/models/mint_libero")
    fi
    for rule in "${MODEL_RULES[@]}"; do
        case "$rule" in
            cache-dtype) prefix="cache_dtype" ;;
            compile) prefix="compile" ;;
            sinusoidal-fp64) prefix="sinusoidal_fp64" ;;
        esac
        "$PYTHON" "$CASE_DIR/tests/cache_dtype_model_ab.py" \
            --backend npu --rule "$rule" --source-root "$MODEL_SOURCE" \
            "${MODEL_CHECKPOINT_ARGS[@]}" \
            --output "$OUTPUT_DIR/${prefix}_model_inference_ab.json" \
            >"$OUTPUT_DIR/${prefix}_model_inference_ab.log" 2>&1
        if [[ "${N2S_RUN_MODEL_TRAINING_AB:-${N2S_RUN_CACHE_DTYPE_TRAINING_AB:-0}}" == "1" ]]; then
            "$PYTHON" "$CASE_DIR/tests/cache_dtype_model_ab.py" \
                --backend npu --rule "$rule" --mode training --source-root "$MODEL_SOURCE" \
                "${MODEL_CHECKPOINT_ARGS[@]}" \
                --output "$OUTPUT_DIR/${prefix}_model_training_ab.json" \
                >"$OUTPUT_DIR/${prefix}_model_training_ab.log" 2>&1
        fi
    done
fi

"$PYTHON" "$CASE_DIR/tests/assemble_model_checks.py" \
    --evidence-dir "$OUTPUT_DIR" --output "$OUTPUT_DIR/model_checks.json" \
    >"$OUTPUT_DIR/model_checks.log" 2>&1

echo "NPU exploratory evidence written to $OUTPUT_DIR"
