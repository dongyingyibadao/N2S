#!/usr/bin/env bash

set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

COMPONENT="${1:-all}"
MINT_REVISION="9e5c72e4044d94c3f77046427db84b84f3f68fb1"
TOKENIZER_REVISION="cf061fe46497f95e768f845f007646a85c883df3"
PI05_BASE_REVISION="b211f3d44c36b6acfcf7ae94a64e8e96f75a64ba"

case "$COMPONENT" in
    checkpoint|tokenizer|base|all) ;;
    *) echo "Usage: $0 [checkpoint|tokenizer|base|all]" >&2; exit 2 ;;
esac

for destination in "$MINT_CHECKPOINT" "$MINT_TOKENIZER" "$MINT_PI05_BASE"; do
    destination="$(realpath -m "$destination")"
    if [[ "$destination" != "$MINT_ASCEND_ROOT/"* ]]; then
        echo "Refusing non-persistent download directory: $destination" >&2
        exit 2
    fi
done

if [[ "$COMPONENT" == "checkpoint" || "$COMPONENT" == "all" ]]; then
    hf download huangrm/MINT-libero \
        --revision "$MINT_REVISION" \
        --local-dir "$MINT_CHECKPOINT"
fi

if [[ "$COMPONENT" == "tokenizer" || "$COMPONENT" == "all" ]]; then
    hf download huangrm/MINT-tokenizer-libero \
        --revision "$TOKENIZER_REVISION" \
        --local-dir "$MINT_TOKENIZER"
fi

if [[ "$COMPONENT" == "base" || "$COMPONENT" == "all" ]]; then
    hf download lerobot/pi05_base \
        --revision "$PI05_BASE_REVISION" \
        --local-dir "$MINT_PI05_BASE"
fi

printf '%s\n' \
    "mint_checkpoint=$MINT_CHECKPOINT" \
    "mint_revision=$MINT_REVISION" \
    "mint_tokenizer=$MINT_TOKENIZER" \
    "tokenizer_revision=$TOKENIZER_REVISION" \
    "pi05_base=$MINT_PI05_BASE" \
    "pi05_base_revision=$PI05_BASE_REVISION"
