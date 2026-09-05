#!/usr/bin/env bash
set -euo pipefail

CASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CUDA_DIR="$CASE_DIR/cuda"
ARCHIVE="${1:-$CUDA_DIR/n2s-cuda-block-validation.tar.gz}"
if [[ -e "$ARCHIVE" || -e "$ARCHIVE.sha256" ]]; then
    echo "refusing to overwrite existing bundle: $ARCHIVE" >&2
    exit 2
fi

FILES=(
    run_cuda_block_checks.sh
    tests/candidate_checks.py
    tests/cache_dtype_ab.py
    tests/runtime_rule_ab.py
    schemas/result.schema.json
    cuda/README.md
    cuda/requirements-cu128.txt
    cuda/preflight.py
    cuda/cuda-validation.schema.json
    cuda/validate_results.py
    cuda/run_bundle.sh
)

(
    cd "$CASE_DIR"
    printf '%s\n' "${FILES[@]}" | LC_ALL=C sort | xargs sha256sum
) >"$CUDA_DIR/BUNDLE_CONTENTS.sha256"
FILES+=(cuda/BUNDLE_CONTENTS.sha256)

mkdir -p "$(dirname "$ARCHIVE")"
(
    cd "$CASE_DIR"
    tar --sort=name --mtime='UTC 2026-08-31' --owner=0 --group=0 --numeric-owner \
        --transform='s,^,n2s-cuda-block/,' \
        --use-compress-program='gzip -n' \
        -cf "$ARCHIVE" "${FILES[@]}"
)
(
    cd "$(dirname "$ARCHIVE")"
    sha256sum "$(basename "$ARCHIVE")"
) >"$ARCHIVE.sha256"
echo "CUDA bundle: $ARCHIVE"
echo "Bundle checksum: $ARCHIVE.sha256"
