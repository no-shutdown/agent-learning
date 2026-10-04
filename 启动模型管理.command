#!/bin/zsh
set -e
cd "${0:A:h}"
export PATH="$HOME/.docker/bin:/opt/homebrew/bin:$PATH"
if ! curl --noproxy '*' --fail --silent --max-time 3 http://127.0.0.1:11434/api/version >/dev/null; then
  open -a Terminal "$PWD/启动模型.command"
fi
docker compose -f compose.models.yaml up -d
for attempt in {1..90}; do
  if curl --noproxy '*' --fail --silent --max-time 2 http://127.0.0.1:3000/health >/dev/null; then
    open http://127.0.0.1:3000
    exit 0
  fi
  sleep 2
done
echo "页面尚未就绪，请执行 docker compose -f compose.models.yaml logs --tail 50。"
exit 1
