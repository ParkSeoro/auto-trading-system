#!/usr/bin/env bash
# ============================================================
#  Crypto Auto-Trading System - Interactive Menu (macOS/Linux)
# ============================================================
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
    echo "[!] 가상환경이 없습니다. 먼저 ./install.sh 를 실행하세요."
    exit 1
fi

PY=".venv/bin/python"

while true; do
    clear
    cat <<EOF

================================================================
  Crypto Auto-Trading System
================================================================

  활성 거래소는 .env의 EXCHANGE (bithumb 기본 / upbit) 에서 설정

  [1] 페이퍼 트레이딩 시작 (가상자본, 안전)
  [2] 백테스트 실행 (과거 데이터)
  [3] 실거래 시작 (주의!)
  [4] 단위 테스트 실행
  [5] .env 파일 편집 (거래소 + API 키)
  [6] 웹 대시보드 시작 (http://localhost:8787)
  [7] AI 전략 진화 (유전 알고리즘 튜닝)
  [0] 종료

EOF
    read -rp "  선택: " choice

    case "$choice" in
        1)
            read -rp "  마켓 [KRW-BTC]: " M; M=${M:-KRW-BTC}
            read -rp "  전략 [ensemble]: " S; S=${S:-ensemble}
            read -rp "  타임프레임 [1d]: " T; T=${T:-1d}
            $PY -m scripts.run_bot --mode paper --markets "$M" --strategy "$S" --timeframe "$T"
            read -rp "Press Enter to continue..." _
            ;;
        2)
            read -rp "  마켓 [KRW-BTC]: " M; M=${M:-KRW-BTC}
            read -rp "  전략 [volatility_breakout]: " S; S=${S:-volatility_breakout}
            read -rp "  캔들 수 [500]: " C; C=${C:-500}
            read -rp "  자본 [1000000]: " K; K=${K:-1000000}
            $PY -m scripts.run_backtest --market "$M" --strategy "$S" --count "$C" --capital "$K"
            read -rp "Press Enter to continue..." _
            ;;
        3)
            if [ ! -f ".env" ]; then
                echo "[ERROR] .env 없음. API 키 설정 먼저."
                read -rp "Press Enter..." _
                continue
            fi
            echo
            echo "[경고] 실거래 모드 - 실제 자금 사용."
            read -rp "  정말 진행? (YES 입력): " C
            [ "$C" != "YES" ] && continue
            read -rp "  마켓 [KRW-BTC]: " M; M=${M:-KRW-BTC}
            read -rp "  전략 [volatility_breakout]: " S; S=${S:-volatility_breakout}
            $PY -m scripts.run_bot --mode live --markets "$M" --strategy "$S"
            read -rp "Press Enter to continue..." _
            ;;
        4)
            $PY -m pytest -v
            read -rp "Press Enter to continue..." _
            ;;
        5)
            [ ! -f ".env" ] && [ -f ".env.example" ] && cp .env.example .env
            "${EDITOR:-nano}" .env
            ;;
        6)
            echo
            echo "웹 대시보드 시작: http://localhost:8787  (Ctrl+C로 중지)"
            $PY -m scripts.run_web
            read -rp "Press Enter to continue..." _
            ;;
        7)
            read -rp "  마켓 [KRW-BTC]: " M; M=${M:-KRW-BTC}
            read -rp "  캔들 수 [800]: " C; C=${C:-800}
            read -rp "  세대 수 [8]: " G; G=${G:-8}
            $PY -m scripts.run_evolve --market "$M" --count "$C" --generations "$G"
            read -rp "Press Enter to continue..." _
            ;;
        0) exit 0 ;;
    esac
done
