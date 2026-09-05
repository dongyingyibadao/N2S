#!/usr/bin/env bash
set -euo pipefail

CUDA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CASE_DIR="$(cd "$CUDA_DIR/.." && pwd)"
if [[ "$#" -gt 1 ]]; then
    echo "usage: $0 [output-directory]" >&2
    exit 2
fi
OUTPUT_DIR="${1:-$CUDA_DIR/results-$(date -u +%Y%m%dT%H%M%SZ)}"
if [[ -e "$OUTPUT_DIR" ]]; then
    echo "refusing existing output path: $OUTPUT_DIR" >&2
    exit 2
fi
mkdir -p "$OUTPUT_DIR"

if [[ ! -f "$CUDA_DIR/BUNDLE_CONTENTS.sha256" ]]; then
    echo "BUNDLE_CONTENTS.sha256 is missing; use the built CUDA archive" >&2
    exit 2
fi
(
    cd "$CASE_DIR"
    sha256sum -c cuda/BUNDLE_CONTENTS.sha256
) >"$OUTPUT_DIR/bundle_verification.log" 2>&1

BOOTSTRAP_PYTHON="${N2S_BOOTSTRAP_PYTHON:-python3.12}"
VENV="${N2S_CUDA_VENV:-$CASE_DIR/.venv}"
if [[ "${N2S_SKIP_INSTALL:-0}" == "1" ]]; then
    PYTHON="${N2S_PYTHON:-python3}"
    printf 'dependency installation skipped; using %s\n' "$PYTHON" >"$OUTPUT_DIR/install.log"
else
    "$BOOTSTRAP_PYTHON" -m venv "$VENV" >"$OUTPUT_DIR/install.log" 2>&1
    PYTHON="$VENV/bin/python"
    "$PYTHON" -m pip install --upgrade "pip==26.2" >>"$OUTPUT_DIR/install.log" 2>&1
    "$PYTHON" -m pip install --no-cache-dir -r "$CUDA_DIR/requirements-cu128.txt" >>"$OUTPUT_DIR/install.log" 2>&1
fi

nvidia-smi -q >"$OUTPUT_DIR/nvidia_smi.log" 2>&1
"$PYTHON" -m pip freeze | LC_ALL=C sort >"$OUTPUT_DIR/pip_freeze.log"
"$PYTHON" "$CUDA_DIR/preflight.py" >"$OUTPUT_DIR/preflight.json"

set +e
N2S_PYTHON="$PYTHON" \
N2S_OUTPUT_DIR="$OUTPUT_DIR" \
"$CASE_DIR/run_cuda_block_checks.sh"
HARNESS_EXIT_CODE=$?
set -e
printf '%d\n' "$HARNESS_EXIT_CODE" >"$OUTPUT_DIR/harness_exit_code.txt"

"$PYTHON" "$CUDA_DIR/validate_results.py" \
    --results "$OUTPUT_DIR" \
    --harness-exit-code "$HARNESS_EXIT_CODE" \
    --output "$OUTPUT_DIR/cuda_validation_manifest.json"
(
    cd "$OUTPUT_DIR"
    find . -maxdepth 1 -type f ! -name SHA256SUMS -printf '%P\n' \
        | LC_ALL=C sort \
        | xargs -r sha256sum
) >"$OUTPUT_DIR/SHA256SUMS"
(
    cd "$OUTPUT_DIR"
    sha256sum -c SHA256SUMS >/dev/null
)

echo "CUDA capture complete: $OUTPUT_DIR"
echo "Return the complete directory, including JSON, logs, SHA256SUMS, and cuda_validation_manifest.json."
