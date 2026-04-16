#!/usr/bin/env bash
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
    echo "[!] 가상환경 없음. ./install.sh 먼저 실행."
    exit 1
fi

PY=".venv/bin/python"

# Ensure web deps are present (auto-install if missing)
if ! "$PY" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
    echo "[INFO] 웹 의존성 누락. fastapi / uvicorn 자동 설치 중..."
    "$PY" -m pip install --upgrade pip >/dev/null
    "$PY" -m pip install -r requirements.txt || {
        echo "[ERROR] 설치 실패. 인터넷 확인 후 재시도."
        exit 1
    }
fi

HOST=${1:-127.0.0.1}
PORT=${2:-8787}
echo "웹 대시보드: http://${HOST}:${PORT}"
"$PY" -m scripts.run_web --host "$HOST" --port "$PORT"
