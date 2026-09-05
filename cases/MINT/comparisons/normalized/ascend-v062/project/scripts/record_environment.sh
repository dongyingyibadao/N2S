#!/usr/bin/env bash

set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/env.sh"

LEROBOT_PROJECT_ROOT="$MINT_ASCEND_ROOT/projects/lerobot-ascend"
PYTHON_ENV_ROOT="$MINT_ASCEND_ROOT/envs/lerobot-npu"
SNAPSHOT_NAME="${1:-ascend_vla_$(date +%Y%m%d_%H%M%S)}"
OUTPUT_DIR="$MINT_ASCEND_ROOT/outputs/manifests/$SNAPSHOT_NAME"
if [[ -e "$OUTPUT_DIR" ]]; then
    echo "Refusing to overwrite existing manifest directory: $OUTPUT_DIR" >&2
    exit 2
fi
mkdir -p "$OUTPUT_DIR"

{
    printf 'created_at=%s\n' "$(date --iso-8601=seconds)"
    printf 'persistent_root=%s\n' "$MINT_ASCEND_ROOT"
    printf 'python=%s\n' "$(command -v python)"
    printf 'python_version=%s\n' "$(python --version 2>&1)"
    printf 'lerobot_project=%s\n' "$LEROBOT_PROJECT_ROOT"
    printf 'mint_project=%s\n' "$MINT_PROJECT_ROOT"
    printf 'python_environment=%s\n' "$PYTHON_ENV_ROOT"
    printf 'python_environment_size=%s\n' "$(du -sh "$PYTHON_ENV_ROOT" | cut -f1)"
    printf 'ascend_toolkit_size=%s\n' "$(du -sh /usr/local/Ascend | cut -f1)"
    printf 'model_root=%s\n' "$MINT_ASCEND_ROOT/models"
    printf 'dataset_root=%s\n' "$HF_LEROBOT_HOME"
    printf 'output_root=%s\n' "$LEROBOT_OUTPUT_ROOT"
    printf 'cache_root=%s\n' "$HF_HOME"
    printf 'mint_load_mode=PYTHONPATH plugin, not pip-installed\n'
} >"$OUTPUT_DIR/storage_and_runtime.txt"

python - <<'PY' >"$OUTPUT_DIR/core_versions.txt"
import accelerate
import lerobot
import torch
import torch_npu
import transformers

print(f"torch={torch.__version__}")
print(f"torch_npu={torch_npu.__version__}")
print(f"transformers={transformers.__version__}")
print(f"lerobot={lerobot.__version__}")
print(f"accelerate={accelerate.__version__}")
print(f"npu_available={torch.npu.is_available()}")
print(f"npu_count={torch.npu.device_count()}")
for index in range(torch.npu.device_count()):
    print(f"npu_{index}={torch.npu.get_device_name(index)}")
PY

python -m pip freeze --all >"$OUTPUT_DIR/pip_freeze.txt"
npu-smi info >"$OUTPUT_DIR/npu_smi.txt" 2>&1
uname -a >"$OUTPUT_DIR/uname.txt"
find /usr/local/Ascend -maxdepth 4 -type f \
    \( -name 'version.cfg' -o -name 'version.info' -o -name 'version.properties' \) \
    -print -exec sed -n '1,120p' {} \; >"$OUTPUT_DIR/ascend_versions.txt" 2>&1

record_repository() {
    local repository="$1"
    local name="$2"
    local fallback_commit="$3"
    if git -C "$repository" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        git -C "$repository" rev-parse HEAD >"$OUTPUT_DIR/${name}_commit.txt"
        git -C "$repository" status --short >"$OUTPUT_DIR/${name}_status.txt"
        git -C "$repository" diff --binary >"$OUTPUT_DIR/${name}_npu_changes.patch"
    else
        printf '%s\n' "$fallback_commit" >"$OUTPUT_DIR/${name}_commit.txt"
        printf 'deployment copy without .git metadata\n' >"$OUTPUT_DIR/${name}_status.txt"
        : >"$OUTPUT_DIR/${name}_npu_changes.patch"
    fi
}

record_repository "$LEROBOT_PROJECT_ROOT" lerobot "deployment commit unavailable"
record_repository "$MINT_PROJECT_ROOT" mint "59fa23d0537f545ca07b7d111a9f5697bbabe11e"
find "$MINT_PROJECT_ROOT/lerobot_policy_mint" "$MINT_PROJECT_ROOT/scripts/ascend" \
    -type f ! -path '*/__pycache__/*' -exec sha256sum {} \; \
    >"$OUTPUT_DIR/mint_deployment_sha256.txt"
find "$LEROBOT_PROJECT_ROOT/src/lerobot" "$LEROBOT_PROJECT_ROOT/scripts/ascend" \
    -type f ! -path '*/__pycache__/*' -exec sha256sum {} \; \
    >"$OUTPUT_DIR/lerobot_deployment_sha256.txt"

printf 'environment_manifest=%s\n' "$OUTPUT_DIR"
