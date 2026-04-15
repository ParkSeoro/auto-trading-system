#!/usr/bin/env bash
# 백테스트 실행
cd "$(dirname "$0")"
[ ! -x ".venv/bin/python" ] && { echo "install.sh 를 먼저 실행하세요."; exit 1; }

MARKET="${1:-KRW-BTC}"
STRATEGY="${2:-volatility_breakout}"
COUNT="${3:-500}"
CAPITAL="${4:-1000000}"

.venv/bin/python -m scripts.run_backtest --market "$MARKET" --strategy "$STRATEGY" --count "$COUNT" --capital "$CAPITAL"
