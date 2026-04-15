#!/usr/bin/env bash
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
    echo "[!] 가상환경 없음. ./install.sh 먼저 실행."
    exit 1
fi
HOST=${1:-127.0.0.1}
PORT=${2:-8787}
echo "웹 대시보드: http://${HOST}:${PORT}"
.venv/bin/python -m scripts.run_web --host "$HOST" --port "$PORT"
