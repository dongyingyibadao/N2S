#!/usr/bin/env bash

if [[ -z "${ASCEND_VLA_PERSISTENT_ROOT:-}" ]]; then
    echo "必须先显式设置 ASCEND_VLA_PERSISTENT_ROOT" >&2
    return 2 2>/dev/null || exit 2
fi

SCRIPT_PATH="$(realpath "${BASH_SOURCE[0]}")"
if [[ "$SCRIPT_PATH" == /opt/ascend-vla/src/* ]]; then
    source /opt/ascend-vla/activate-v062.sh || {
        status=$?
        return "$status" 2>/dev/null || exit "$status"
    }
    export MINT_ASCEND_ROOT="$ASCEND_VLA_PERSISTENT_ROOT"
    MINT_PROJECT_ROOT=/opt/ascend-vla/src/MINT
else
    export MINT_ASCEND_ROOT="$ASCEND_VLA_PERSISTENT_ROOT"

    LEROBOT_ENV="$MINT_ASCEND_ROOT/projects/lerobot-ascend/scripts/ascend/env.sh"
    if [[ ! -f "$LEROBOT_ENV" ]]; then
        echo "LeRobot Ascend environment is missing: $LEROBOT_ENV" >&2
        return 2 2>/dev/null || exit 2
    fi
    source "$LEROBOT_ENV"
    MINT_PROJECT_ROOT="$MINT_ASCEND_ROOT/projects/MINT"
fi

export MINT_PROJECT_ROOT
export MINT_PLUGIN_ROOT="$MINT_PROJECT_ROOT/lerobot_policy_mint"
export PYTHONPATH="$MINT_PLUGIN_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export MINT_CHECKPOINT="$MINT_ASCEND_ROOT/models/mint_libero"
export MINT_TOKENIZER="$MINT_ASCEND_ROOT/models/mint_tokenizer_libero"
export MINT_PI05_BASE="${MINT_PI05_BASE:-$MINT_ASCEND_ROOT/models/pi05_base}"
export MINT_OUTPUT_ROOT="$LEROBOT_OUTPUT_ROOT/mint"

mkdir -p \
    "$MINT_OUTPUT_ROOT" \
    "$MINT_ASCEND_ROOT/models" \
    "$MINT_ASCEND_ROOT/outputs/downloads"
