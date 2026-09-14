#!/usr/bin/env bash
set -euo pipefail

# Download the GGUF weights used by the three-server setup.  The default
# repositories are public Hugging Face quantizations; override them when a
# local or private mirror is preferred.  This script does not start servers.

MODEL_DIR="${MODEL_DIR:-/opt/models}"
HF_BIN="${HF_BIN:-hf}"
RICOH_REPO="${RICOH_REPO:-mmnga-o/Qwen-3-VL-Ricoh-8B-20260227-gguf}"
UNIMUMER_REPO="${UNIMUMER_REPO:-mradermacher/Uni-MuMER-Qwen3.5-4B-i1-GGUF}"
ORNITH_REPO="${ORNITH_REPO:-ornith-ai/Ornith-1.5-35B-A3B-GGUF}"

command -v "$HF_BIN" >/dev/null || {
  echo "hf command not found. Install with: python3 -m pip install -U huggingface_hub" >&2
  exit 1
}
mkdir -p "$MODEL_DIR"

download() {
  local repo="$1" local_dir="$2" include="$3"
  echo "Downloading $repo ($include) -> $local_dir"
  "$HF_BIN" download "$repo" --local-dir "$MODEL_DIR/$local_dir" --include "$include"
}

# Ricoh needs both the Q8 weights and its vision projector.
download "$RICOH_REPO" "Qwen-3-VL-Ricoh-8B-20260227" '*Q8_0.gguf'
download "$RICOH_REPO" "Qwen-3-VL-Ricoh-8B-20260227" '*mmproj-f16.gguf'
# Uni-MuMER and Ornith repositories contain the selected quant plus projector.
download "$UNIMUMER_REPO" "Uni-MuMER-4B-Q4_K_M" '*Q4_K_M*.gguf'
download "$UNIMUMER_REPO" "Uni-MuMER-4B-Q4_K_M" '*mmproj*.gguf'
download "$ORNITH_REPO" "Ornith-1.5-35B-A3B-Q8_0" '*Q8_0*.gguf'
download "$ORNITH_REPO" "Ornith-1.5-35B-A3B-Q8_0" '*mmproj*.gguf'

echo "Model files are under $MODEL_DIR. Configure llama-server paths and run scoring check."
