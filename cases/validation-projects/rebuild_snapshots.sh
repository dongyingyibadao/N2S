#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMP_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/n2s-validation-sources-XXXXXX")"
trap 'rm -rf -- "$TEMP_ROOT"' EXIT

materialize() {
    local name="$1"
    local remote="$2"
    local revision="$3"
    shift 3
    local repository="$TEMP_ROOT/$name.git"
    local target="$SCRIPT_DIR/$name"

    git init --quiet "$repository"
    git -C "$repository" remote add origin "$remote"
    git -C "$repository" fetch --quiet --depth=1 origin "$revision"
    if [[ "$(git -C "$repository" rev-parse FETCH_HEAD)" != "$revision" ]]; then
        echo "Fetched revision differs for $name" >&2
        return 2
    fi

    mkdir -p "$target"
    find "$target" -mindepth 1 -delete
    git -C "$repository" archive FETCH_HEAD -- "$@" | tar -x -C "$target"
    printf '%s\n' "$remote" >"$target/REMOTE"
    printf '%s\n' "$revision" >"$target/REVISION"
    find "$target" -type d -exec chmod 0755 {} +
    find "$target" -type f -exec chmod 0644 {} +
    (
        cd "$target"
        find . -type f ! -name SHA256SUMS -printf '%P\n' | LC_ALL=C sort | xargs -r sha256sum
    ) >"$target/SHA256SUMS"
    (
        cd "$target"
        sha256sum -c SHA256SUMS >/dev/null
    )
}

materialize \
    lerobot-4aaff99 \
    https://github.com/huggingface/lerobot.git \
    4aaff99be4a1d81568c08c8f0296b41b40c99ec4 \
    LICENSE \
    pyproject.toml \
    src/lerobot/utils/device_utils.py \
    src/lerobot/policies/common/vla_utils.py \
    src/lerobot/policies/pi0/configuration_pi0.py \
    src/lerobot/policies/pi0/modeling_pi0.py \
    src/lerobot/policies/smolvla/configuration_smolvla.py \
    src/lerobot/policies/smolvla/modeling_smolvla.py \
    src/lerobot/policies/smolvla/smolvlm_with_expert.py \
    tests/utils/test_device_utils.py

materialize \
    openpi-215abfb \
    https://github.com/Physical-Intelligence/openpi.git \
    215abfb217dbac7d5f1273282331b9b1866c0479 \
    LICENSE \
    LICENSE_GEMMA.txt \
    pyproject.toml \
    src/openpi/models/model.py \
    src/openpi/models/pi0_config.py \
    src/openpi/models_pytorch/gemma_pytorch.py \
    src/openpi/models_pytorch/pi0_pytorch.py \
    src/openpi/models/pi0_test.py

echo "Rebuilt pinned non-MINT snapshots under $SCRIPT_DIR"
