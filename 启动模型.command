#!/bin/zsh
export PATH="/opt/homebrew/bin:$PATH"
if curl --noproxy '*' --fail --silent --max-time 3 http://127.0.0.1:11434/api/version; then
  echo "\nOllama 已运行。"
  exit 0
fi
export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_CONTEXT_LENGTH=8192
export OLLAMA_NUM_PARALLEL=1
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_FLASH_ATTENTION=1
export OLLAMA_NO_CLOUD=1
exec ollama serve
