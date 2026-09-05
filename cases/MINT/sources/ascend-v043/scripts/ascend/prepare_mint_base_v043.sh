#!/usr/bin/env bash

set -eo pipefail

ROOT="${ASCEND_VLA_PERSISTENT_ROOT:?必须先显式设置 ASCEND_VLA_PERSISTENT_ROOT}"
SOURCE_MODEL="$ROOT/models/pi05_base"
SOURCE_PROCESSOR="$ROOT/models/mint_libero"
VIEW="$ROOT/models/compat/pi05_base_for_mint_v043"

if [[ ! -f "$SOURCE_MODEL/model.safetensors" ]]; then
    echo "Missing PI0.5 base weights: $SOURCE_MODEL/model.safetensors" >&2
    exit 2
fi

required_processor_files=(
    policy_preprocessor.json
    policy_postprocessor.json
    policy_preprocessor_step_2_normalizer_processor.safetensors
    policy_postprocessor_step_0_unnormalizer_processor.safetensors
)
for filename in "${required_processor_files[@]}"; do
    if [[ ! -f "$SOURCE_PROCESSOR/$filename" ]]; then
        echo "Missing MINT processor metadata: $SOURCE_PROCESSOR/$filename" >&2
        exit 2
    fi
done

if [[ -e "$VIEW" ]]; then
    echo "Refusing to overwrite existing compatibility view: $VIEW" >&2
    exit 2
fi

mkdir -p "$VIEW"
ln -s "$SOURCE_MODEL/model.safetensors" "$VIEW/model.safetensors"
for filename in "${required_processor_files[@]}"; do
    ln -s "$SOURCE_PROCESSOR/$filename" "$VIEW/$filename"
done

printf '%s\n' \
    "purpose=MINT 0.4.3 initialization from PI0.5 backbone with MINT processor metadata" \
    "model_weights=$SOURCE_MODEL/model.safetensors" \
    "processor_metadata=$SOURCE_PROCESSOR" \
    "view=$VIEW" >"$VIEW/ORIGIN.txt"

du -sh "$VIEW"
