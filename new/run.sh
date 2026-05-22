#!/usr/bin/env bash
# NOVA launcher — sets up CUDA paths and launches the assistant.
# Fixes CUDA 12/13 mismatch for CTranslate2 (faster-whisper).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CUDA_LIB_DIR="$HOME/.conda/envs/NOVA/lib/python3.10/site-packages/nvidia/cu13/lib"

export LD_LIBRARY_PATH="$CUDA_LIB_DIR:${LD_LIBRARY_PATH:-}"

cd "$SCRIPT_DIR"
exec python -m nova "$@"
