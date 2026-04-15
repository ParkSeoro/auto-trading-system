#!/usr/bin/env bash
# Paper (모의) 트레이딩
cd "$(dirname "$0")"
[ ! -x ".venv/bin/python" ] && { echo "install.sh 를 먼저 실행하세요."; exit 1; }

MARKETS="${1:-KRW-BTC}"
STRATEGY="${2:-ensemble}"
TIMEFRAME="${3:-1d}"

echo "=== 페이퍼 트레이딩 ==="
echo "  마켓: $MARKETS / 전략: $STRATEGY / TF: $TIMEFRAME"
.venv/bin/python -m scripts.run_bot --mode paper --markets "$MARKETS" --strategy "$STRATEGY" --timeframe "$TIMEFRAME"
