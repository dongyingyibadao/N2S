#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

MODEL_DIR="${1:-$MINT_PI05_BASE}"
PART_SIZE=3616791468
FULL_SIZE=14467165872
FULL_SHA256="0eb11ca9587678c1d2ef8cf32807c29f8ce53a2bfdfc1aa4a4c96f16fca59b0f"
PART_SHA256=(
    "20454f3800c55392ac8684fab84da72af52f0792fe9f29e2f27cdc9f7b295943"
    "441ca220e4bbfac2dfbf37af8a1435e5677f2d87a83dbddc09f9921d6e456073"
    "2d5919b6784bff555e612293ab54bb22617ca7c9c095e1ef625dd615ca1d067d"
    "8d9d1f8a221d64b267f59a3d483a454aaf1dddba6760cba86bc9b5327df84b83"
)
TARGET="$MODEL_DIR/model.safetensors"
TEMP_TARGET="$MODEL_DIR/model.safetensors.assembling"

if [[ -e "$TARGET" ]]; then
    actual="$(sha256sum "$TARGET" | cut -d ' ' -f 1)"
    if [[ "$actual" == "$FULL_SHA256" ]]; then
        printf 'PI0.5 base is already complete: %s\n' "$TARGET"
        exit 0
    fi
    echo "Refusing to overwrite an existing target with SHA256 $actual" >&2
    exit 2
fi
if [[ -e "$TEMP_TARGET" ]]; then
    echo "Refusing to overwrite an existing assembly file: $TEMP_TARGET" >&2
    exit 2
fi

for index in 0 1 2 3; do
    part="$MODEL_DIR/upload_clean_part${index}.tmp"
    if [[ ! -f "$part" ]]; then
        echo "Missing upload part: $part" >&2
        exit 2
    fi
    size="$(stat -c '%s' "$part")"
    if [[ "$size" != "$PART_SIZE" ]]; then
        echo "Size mismatch for $part: expected=$PART_SIZE actual=$size" >&2
        exit 2
    fi
    actual="$(sha256sum "$part" | cut -d ' ' -f 1)"
    if [[ "$actual" != "${PART_SHA256[$index]}" ]]; then
        echo "SHA256 mismatch for $part: expected=${PART_SHA256[$index]} actual=$actual" >&2
        exit 2
    fi
    printf 'part%s verified: size=%s sha256=%s\n' "$index" "$size" "$actual"
done

dd if="$MODEL_DIR/upload_clean_part0.tmp" of="$TEMP_TARGET" bs=16M status=progress
for index in 1 2 3; do
    dd if="$MODEL_DIR/upload_clean_part${index}.tmp" of="$TEMP_TARGET" \
        bs=16M oflag=append conv=notrunc status=progress
done

actual_size="$(stat -c '%s' "$TEMP_TARGET")"
if [[ "$actual_size" != "$FULL_SIZE" ]]; then
    echo "Assembled size mismatch: expected=$FULL_SIZE actual=$actual_size" >&2
    exit 2
fi
actual_sha256="$(sha256sum "$TEMP_TARGET" | cut -d ' ' -f 1)"
if [[ "$actual_sha256" != "$FULL_SHA256" ]]; then
    echo "Assembled SHA256 mismatch: expected=$FULL_SHA256 actual=$actual_sha256" >&2
    exit 2
fi

mv "$TEMP_TARGET" "$TARGET"
printf '%s  %s\n' "$FULL_SHA256" "$(basename -- "$TARGET")" >"$MODEL_DIR/model.safetensors.sha256"
printf 'PI0.5 base assembled and verified: %s\n' "$TARGET"
