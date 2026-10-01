#!/bin/sh
set -eu
backend_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export GGML_BACKEND_PATH="$backend_dir"
export LD_LIBRARY_PATH="$backend_dir:/usr/local/nvidia/lib:/usr/local/nvidia/lib64:/usr/local/cuda-12.8/targets/x86_64-linux/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
exec "$backend_dir/llama-server.bin" "$@"
