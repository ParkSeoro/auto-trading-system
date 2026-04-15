#!/usr/bin/env bash
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
    echo "[!] 가상환경 없음. ./install.sh 먼저 실행."
    exit 1
fi
MARKET=${1:-KRW-BTC}
COUNT=${2:-800}
GEN=${3:-8}
.venv/bin/python -m scripts.run_evolve --market "$MARKET" --count "$COUNT" --generations "$GEN"
