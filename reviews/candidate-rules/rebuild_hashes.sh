#!/usr/bin/env bash
set -euo pipefail

REVIEW_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
(
    cd "$REVIEW_DIR"
    find . -maxdepth 1 -type f ! -name SHA256SUMS -printf '%P\n' \
        | LC_ALL=C sort \
        | xargs -r sha256sum
) >"$REVIEW_DIR/SHA256SUMS"
(
    cd "$REVIEW_DIR"
    sha256sum -c SHA256SUMS >/dev/null
)
echo "Maintainer review hashes rebuilt: $REVIEW_DIR/SHA256SUMS"
