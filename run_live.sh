#!/usr/bin/env bash
# 실거래 - 주의
cd "$(dirname "$0")"
[ ! -x ".venv/bin/python" ] && { echo "install.sh 를 먼저 실행하세요."; exit 1; }
[ ! -f ".env" ] && { echo "[ERROR] .env 없음."; exit 1; }

echo "[경고] 실거래 모드 - 실제 자금 사용"
read -rp "  정말 진행? (YES 입력 시 실행): " C
[ "$C" != "YES" ] && { echo "취소됨."; exit 0; }

MARKETS="${1:-KRW-BTC}"
STRATEGY="${2:-volatility_breakout}"
.venv/bin/python -m scripts.run_bot --mode live --markets "$MARKETS" --strategy "$STRATEGY"
