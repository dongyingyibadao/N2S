#!/usr/bin/env bash

set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RUN_TAG="${1:-mint_8npu_12h_$(date +%Y%m%d_%H%M%S)}"
DURATION="${2:-12h}"
DEVICE_IDS_CSV="${3:-0,1,2,3,4,5,6,7}"

MINT_NUM_PROCESSES=8 exec "$SCRIPT_DIR/launch_mint_4npu_12h.sh" \
    "$RUN_TAG" "$DURATION" "$DEVICE_IDS_CSV"
