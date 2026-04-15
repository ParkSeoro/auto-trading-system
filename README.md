# 가상화폐 자동매매 시스템 (Crypto Auto-Trading System)

Python 기반의 실제 작동 가능한 가상화폐 자동매매 프로그램입니다.
**빗썸(Bithumb, 기본값) 및 업비트(Upbit)** 거래소 API와 연동되며, 주식과는 다른
**가상화폐 전용 로직**(24/7 거래, 높은 변동성 대응, 소수점 매매, 변동성 돌파 전략 등)을 구현합니다.
`.env`의 `EXCHANGE=bithumb|upbit` 한 줄로 거래소를 전환할 수 있습니다.

> 주식용 `Reactivate automated trading program` 프로젝트와 동일한 레이어드 아키텍처
> (Exchange → Data → Strategy → Risk → Executor → Bot)를 유지하되,
> 전략 · 리스크 · 데이터 계층을 가상화폐 시장 특성에 맞춰 전면 재구현했습니다.

---

## 주식과 다른 가상화폐 전용 로직

| 영역 | 주식 시스템 | 본 가상화폐 시스템 |
|------|------------|------------------|
| 거래 시간 | 평일 09:00–15:30 | **24시간 365일** 연속 루프 |
| 주문 수량 | 정수 주식 수 | **소수점 수량** (KRW 금액 기준 매수) |
| 주문 종류 | 지정가/시장가 | 빗썸/업비트 규격 (`bid/ask`, `market`, `limit`) |
| 데이터 단위 | 일봉 중심 | **분봉/시간봉/일봉 멀티-타임프레임** |
| 대표 전략 | 이동평균 크로스오버 | **변동성 돌파(Larry Williams)**, 그리드, RSI-역추세 |
| 리스크 | 고정 % 손절 | **ATR 기반 동적 손절**, 플래시 크래시 킬 스위치 |
| 수수료 | ~0.015% | **빗썸 0.25% / 업비트 0.05%** 자동 반영, 최소 주문액(빗썸 1,000 / 업비트 5,000 KRW) 제약 |
| 시장 단절 | 서킷브레이커 | 연속 거래 → **최대 낙폭(MDD) 기반 일시 중단** |

---

## 아키텍처

```
src/
├── bot.py                  # 메인 트레이딩 루프 (24/7)
├── exchanges/
│   ├── base.py             # 거래소 인터페이스 (Protocol)
│   ├── bithumb.py          # 빗썸 REST API (HMAC-SHA512 서명) — 기본
│   ├── upbit.py            # 업비트 REST API (JWT 서명)
│   └── __init__.py         # build_exchange() 팩토리 (EXCHANGE env 기반)
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

---

## 🪟 Windows 빠른 설치 (가장 쉬움)

파일을 전부 `C:\Users\psr15\Desktop\crypto` 에 복사하거나 `git clone` 했다고 가정합니다.

### 1단계. Python 설치 (최초 1회)
- https://www.python.org/downloads/ 에서 **Python 3.10 이상** 다운로드
- 설치 시 **"Add python.exe to PATH"** 체크 필수

### 2단계. 자동 설치
탐색기에서 `C:\Users\psr15\Desktop\crypto` 로 이동 후 **`install.bat` 더블클릭**
- 가상환경(.venv) 자동 생성
- 필요한 라이브러리 자동 설치
- `.env` 자동 생성 (기본 `EXCHANGE=bithumb`)
- 단위 테스트 자동 실행 (61개)

> **한글이 깨져 보이면?** 배치파일 자체는 ASCII 전용으로 작성되어 깨지지 않습니다.
> Python 출력 로그가 깨질 경우 배치파일 상단 `chcp 65001` 이 자동 적용되므로 Windows 10 이상에서는 정상 표시됩니다.

### 3단계. (선택) API 키 입력
실거래(LIVE)를 할 경우에만 필요. 페이퍼 트레이딩과 백테스트는 키 없이 가능.
- 메모장으로 `.env` 파일 열기
- **빗썸(기본):** `EXCHANGE=bithumb` 유지 후,
  `BITHUMB_API_KEY`, `BITHUMB_SECRET_KEY` 에 빗썸 [Open API 키](https://www.bithumb.com/u1/US127) 입력
- **업비트 사용 시:** `EXCHANGE=upbit` 로 바꾼 뒤
  `UPBIT_ACCESS_KEY`, `UPBIT_SECRET_KEY` 에 업비트 [Open API 키](https://upbit.com/mypage/open_api_management) 입력

### 4단계. 실행 — **`start.bat` 더블클릭**하면 메뉴가 뜹니다
```
[1] 페이퍼 트레이딩 시작 (가상자본, 안전)
[2] 백테스트 실행 (과거 데이터)
[3] 실거래 시작 (주의!)
[4] 단위 테스트 실행
[5] .env 파일 열어 API 키 설정
```

또는 개별 실행:

| 파일 | 기능 |
|------|------|
| `install.bat`       | 최초 설치 (가상환경 · 라이브러리 · 테스트) |
| `start.bat`         | **메뉴 UI** — 초보자 추천 |
| `run_paper.bat`     | 페이퍼 트레이딩 (기본: KRW-BTC, 앙상블) |
| `run_backtest.bat`  | 백테스트 (기본: KRW-BTC, 500봉) |
| `run_live.bat`      | 실거래 (YES 확인 필요) |
| `run_tests.bat`     | 단위 테스트 실행 |

**배치파일 인수 지정:**
```cmd
run_paper.bat KRW-BTC,KRW-ETH ensemble 1h
run_backtest.bat KRW-BTC volatility_breakout 1000 2000000
run_live.bat KRW-BTC volatility_breakout
```

**거래소 전환(런타임):** 모든 스크립트는 `--exchange bithumb|upbit` 플래그도 지원합니다.
```cmd
python -m scripts.run_bot --exchange bithumb --mode paper --markets KRW-BTC --strategy ensemble
python -m scripts.run_backtest --exchange upbit  --market KRW-BTC --strategy volatility_breakout
```
시장 코드는 빗썸/업비트 공통 `KRW-BTC` 형식을 쓰며, 빗썸 내부에서는
`BTC_KRW` 로 자동 변환되어 전송됩니다.

---

## 🐧 macOS / Linux 설치

```bash
./install.sh                  # 최초 1회
./start.sh                    # 메뉴 실행
# 또는
./run_paper.sh KRW-BTC ensemble 1d
./run_backtest.sh KRW-BTC volatility_breakout 500 1000000
./run_live.sh
./run_tests.sh
```

---

## 수동 설치 (고급 사용자)

```bash
python -m venv .venv
source .venv/bin/activate         # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # Windows: copy .env.example .env

python -m scripts.run_bot --mode paper --markets KRW-BTC,KRW-ETH --strategy ensemble
python -m scripts.run_backtest --market KRW-BTC --strategy volatility_breakout \
    --from 2024-01-01 --to 2024-12-31 --capital 1000000
pytest -v
```

---

## 경고

- 본 소프트웨어는 **교육 및 연구 목적**으로 제공됩니다.
- 실거래 손실에 대해 제작자는 책임지지 않습니다.
- 반드시 **소액으로 검증** 후 사용하세요.
- API 키는 절대 커밋하지 말고 `.env`로만 관리하세요.
