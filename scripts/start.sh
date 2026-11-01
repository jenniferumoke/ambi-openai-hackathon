#!/bin/sh
set -eu
cd "$(dirname "$0")/.."

if command -v uv >/dev/null 2>&1; then
  AMBI_UV=uv
elif [ -x "$HOME/.local/bin/uv" ]; then
  AMBI_UV="$HOME/.local/bin/uv"
else
  echo 'Install uv first: https://docs.astral.sh/uv/getting-started/installation/'
  exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
  echo 'Install Node.js 22 or newer, then run this command again.'
  exit 1
fi
if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  echo 'Created .env. Add OPENAI_API_KEY there to enable voice; local camera and memory work without it.'
fi
"$AMBI_UV" sync --locked --python 3.12
if [ ! -d ui/node_modules ]; then
  (cd ui && npm ci)
fi
(cd ui && npm run build)
exec "$AMBI_UV" run --locked python server.py --open "$@"
