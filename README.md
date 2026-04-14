# 가상화폐 자동매매 시스템 (Crypto Auto-Trading System)

Python 기반의 실제 작동 가능한 가상화폐 자동매매 프로그램입니다.
업비트(Upbit) 거래소 API와 연동되며, 주식과는 다른 **가상화폐 전용 로직**(24/7 거래,
높은 변동성 대응, 소수점 매매, 변동성 돌파 전략 등)을 구현합니다.

> 주식용 `Reactivate automated trading program` 프로젝트와 동일한 레이어드 아키텍처
> (Exchange → Data → Strategy → Risk → Executor → Bot)를 유지하되,
> 전략 · 리스크 · 데이터 계층을 가상화폐 시장 특성에 맞춰 전면 재구현했습니다.

---

## 주식과 다른 가상화폐 전용 로직

| 영역 | 주식 시스템 | 본 가상화폐 시스템 |
|------|------------|------------------|
| 거래 시간 | 평일 09:00–15:30 | **24시간 365일** 연속 루프 |
| 주문 수량 | 정수 주식 수 | **소수점 수량** (KRW 금액 기준 매수) |
| 주문 종류 | 지정가/시장가 | 업비트 규격(`price`, `market`, `limit`) |
| 데이터 단위 | 일봉 중심 | **분봉/시간봉/일봉 멀티-타임프레임** |
| 대표 전략 | 이동평균 크로스오버 | **변동성 돌파(Larry Williams)**, 그리드, RSI-역추세 |
| 리스크 | 고정 % 손절 | **ATR 기반 동적 손절**, 플래시 크래시 킬 스위치 |
| 수수료 | ~0.015% | 업비트 0.05% 반영, 최소 주문액 5,000 KRW 제약 |
| 시장 단절 | 서킷브레이커 | 연속 거래 → **최대 낙폭(MDD) 기반 일시 중단** |

---

## 아키텍처

```
src/
├── bot.py                  # 메인 트레이딩 루프 (24/7)
├── exchanges/
│   ├── base.py             # 거래소 인터페이스 (Protocol)
│   └── upbit.py            # 업비트 REST API (JWT 서명)
├── data/
│   └── market_data.py      # OHLCV 캐시 · 멀티-TF 수집
├── indicators/
│   └── technical.py        # RSI, MACD, BB, ATR, OBV, EMA, VWAP
├── strategies/
│   ├── base.py             # Strategy 추상 클래스, Signal
│   ├── volatility_breakout.py  # 래리 윌리엄스 변동성 돌파 (K값)
│   ├── rsi_mean_reversion.py
│   ├── bollinger_breakout.py
│   ├── grid_trading.py     # 횡보장 그리드
│   └── ensemble.py         # 다중 전략 투표
├── risk/
│   └── risk_manager.py     # ATR 포지션 사이징, SL/TP, MDD 킬 스위치
├── execution/
│   └── executor.py         # 주문 실행 (실거래 / 페이퍼)
├── backtesting/
│   └── backtester.py       # 이벤트-드리븐 백테스터
├── storage/
│   └── db.py               # SQLite 거래 로그
└── utils/
    ├── logger.py
    └── notifier.py         # (옵션) 디스코드/슬랙 웹훅
```

---

## 설치

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# .env 파일을 열어 UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY 입력
```

## 실행

### 1) 페이퍼 트레이딩 (안전 · 권장 첫 실행)

```bash
python -m scripts.run_bot --mode paper --markets KRW-BTC,KRW-ETH --strategy ensemble
```

### 2) 백테스팅

```bash
python -m scripts.run_backtest \
    --market KRW-BTC \
    --strategy volatility_breakout \
    --from 2024-01-01 --to 2024-12-31 \
    --capital 1000000
```

### 3) 실거래 (⚠️ 반드시 페이퍼로 검증 후)

```bash
python -m scripts.run_bot --mode live --markets KRW-BTC --strategy volatility_breakout
```

## 테스트

```bash
pytest -v
```

---

## 경고

- 본 소프트웨어는 **교육 및 연구 목적**으로 제공됩니다.
- 실거래 손실에 대해 제작자는 책임지지 않습니다.
- 반드시 **소액으로 검증** 후 사용하세요.
- API 키는 절대 커밋하지 말고 `.env`로만 관리하세요.
