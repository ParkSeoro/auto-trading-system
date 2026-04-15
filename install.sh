#!/usr/bin/env bash
# ============================================================
#  Crypto Auto-Trading System - macOS/Linux Installer
# ============================================================
set -e

cd "$(dirname "$0")"

echo
echo "================================================================"
echo "  Crypto Auto-Trading System - Installation"
echo "  설치 경로: $(pwd)"
echo "================================================================"
echo

# 1) Python 확인
echo "[1/5] Python 설치 확인 중..."
if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo
    echo "[ERROR] Python이 설치되어 있지 않습니다."
    echo "  https://www.python.org/downloads/ 에서 Python 3.10 이상을 설치 후 재실행하세요."
    exit 1
fi
echo "    - $($PY --version) 발견."

# 2) 가상환경
echo
echo "[2/5] 가상환경(.venv) 생성..."
if [ -d ".venv" ]; then
    echo "    - 기존 가상환경 사용."
else
    $PY -m venv .venv
    echo "    - .venv 생성 완료."
fi

# shellcheck source=/dev/null
. .venv/bin/activate

# 3) 의존성 설치
echo
echo "[3/5] pip 업그레이드 및 라이브러리 설치 (수 분 소요)..."
python -m pip install --upgrade pip >/dev/null
python -m pip install -r requirements.txt

# 4) .env
echo
echo "[4/5] .env 설정 파일 준비..."
if [ -f ".env" ]; then
    echo "    - 기존 .env 유지."
else
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "    - .env 생성됨. UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY 를 입력하세요."
    fi
fi

# 5) 테스트
echo
echo "[5/5] 설치 확인 테스트 실행..."
if python -m pytest -q; then
    echo "    - 전체 테스트 통과."
else
    echo "[WARN] 일부 테스트 실패. 의존성은 설치되었습니다."
fi

echo
echo "================================================================"
echo "  설치 완료!"
echo
echo "  다음 단계:"
echo "    1) nano .env 로 API 키를 입력 (라이브 거래 시에만 필요)"
echo "    2) ./run_paper.sh 또는 ./start.sh 로 실행"
echo "================================================================"
echo
