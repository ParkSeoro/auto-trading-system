"""FastAPI application — crypto trading dashboard.

Endpoints
---------
- ``GET  /``                   static SPA
- ``GET  /api/status``         bot state + config
- ``GET  /api/exchanges``      list supported exchanges
- ``GET  /api/strategies``     list available strategies
- ``GET  /api/equity``         equity curve history (SQLite)
- ``GET  /api/trades``         recent trades (SQLite)
- ``GET  /api/positions``      current positions (from live bot if running)
- ``GET  /api/weights``        AI ensemble weights (if available)
- ``GET  /api/logs``           in-memory bot activity log
- ``GET  /api/analytics``      win rate / PF / Sharpe / MDD / realised PnL
- ``GET  /api/signals``        live signal from every strategy for one market
- ``GET  /api/chart``          OHLCV + indicators (RSI, BB, MACD) for chart
- ``GET  /api/watchlist``      instant ticker snapshots for multiple markets
- ``POST /api/backtest``       run a backtest and return summary+equity curve
- ``POST /api/start``          start the bot (paper/live)
- ``POST /api/stop``           stop the bot
- ``GET  /api/ticker/{mkt}``   instant ticker snapshot for a single market
- ``WS   /ws``                 push-based live updates (1 s heartbeat)

The dashboard is intentionally single-page and dependency-free
(vanilla HTML/JS/CSS) so it works even when the user is offline,
with API calls proxied via the local FastAPI server.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config.settings import settings
from src.data import candles_to_dataframe
from src.exchanges import build_exchange
from src.indicators import atr, bollinger_bands, macd, rsi
from src.strategies import STRATEGY_REGISTRY, get_strategy
from src.utils.log_buffer import attach_to_root
from src.web.analytics import compute_analytics
from src.web.bot_manager import BotManager

STATIC_DIR = Path(__file__).resolve().parent / "static"


# ----------------------------------------------------------------------
# Request schemas
# ----------------------------------------------------------------------
class StartRequest(BaseModel):
    mode: str = Field("paper", pattern="^(paper|live)$")
    markets: List[str] = Field(default_factory=lambda: ["KRW-BTC"])
    strategy: str = "adaptive_ensemble"
    timeframe: str = "1d"
    exchange: Optional[str] = None  # bithumb | upbit | None -> settings


class BacktestRequest(BaseModel):
    market: str = "KRW-BTC"
    strategy: str = "volatility_breakout"
    timeframe: str = "1d"
    count: int = Field(300, ge=30, le=2000)
    capital: float = Field(1_000_000.0, gt=0.0)
    exchange: Optional[str] = None


# ----------------------------------------------------------------------
# Lightweight read helpers (no ORM on purpose)
# ----------------------------------------------------------------------
def _query(path: Path, sql: str, params: tuple = ()) -> List[dict]:
    if not path.exists():
        return []
    try:
        with sqlite3.connect(str(path)) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
    except sqlite3.Error:
        return []


def _read_equity(limit: int = 500) -> List[dict]:
    rows = _query(
        settings.db_path,
        "SELECT ts, equity, cash, mode FROM equity_history ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    return list(reversed(rows))


def _read_trades(limit: int = 100) -> List[dict]:
    rows = _query(
        settings.db_path,
        "SELECT ts, market, side, price, quantity, funds, fee, mode, strategy, reason "
        "FROM trades ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    return rows


def _read_weights() -> dict:
    wp = settings.data_dir / "weights.json"
    if not wp.exists():
        return {}
    try:
        return json.loads(wp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _read_best_params() -> dict:
    bp = settings.data_dir / "best_params.json"
    if not bp.exists():
        return {}
    try:
        return json.loads(bp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


# ----------------------------------------------------------------------
# Indicator / signal helpers
# ----------------------------------------------------------------------
def _indicators_payload(df: pd.DataFrame) -> dict:
    close = df["close"]
    rsi14 = rsi(close, 14)
    up, mid, lo = bollinger_bands(close, 20, 2.0)
    macd_line, sig_line, hist = macd(close, 12, 26, 9)
    atr14 = atr(df["high"], df["low"], close, 14)

    def _ser(s):
        return [None if pd.isna(v) else float(v) for v in s.tolist()]

    return {
        "rsi14": _ser(rsi14),
        "bb_upper": _ser(up),
        "bb_middle": _ser(mid),
        "bb_lower": _ser(lo),
        "macd": _ser(macd_line),
        "macd_signal": _ser(sig_line),
        "macd_hist": _ser(hist),
        "atr14": _ser(atr14),
    }


def _signals_for(df: pd.DataFrame, position: Optional[dict] = None) -> List[dict]:
    """Ask every registered strategy for its opinion on the given df."""
    out: List[dict] = []
    names = list(STRATEGY_REGISTRY.keys())
    for name in names:
        try:
            strat = get_strategy(name)
            sig = strat.generate(df, position=position)
            out.append({
                "strategy": name,
                "type": sig.type.value,
                "confidence": round(float(sig.confidence), 3),
                "reason": sig.reason,
            })
        except Exception as exc:
            out.append({
                "strategy": name,
                "type": "error",
                "confidence": 0.0,
                "reason": str(exc),
            })
    return out


# ----------------------------------------------------------------------
# App factory
# ----------------------------------------------------------------------
def create_app(manager: Optional[BotManager] = None) -> FastAPI:
    # Make sure the in-memory log buffer is attached even if no logger call
    # has happened yet in this process.
    attach_to_root()

    mgr = manager or BotManager()
    app = FastAPI(
        title="Crypto Auto-Trading Dashboard",
        description="Bithumb / Upbit 자동매매 대시보드 · AI 자가진화 엔진 지원",
        version="1.1",
    )

    # ------------------------------------------------------------------
    # Basic state
    # ------------------------------------------------------------------
    @app.get("/api/status")
    def api_status():
        st = mgr.status().to_dict()
        st["server_time"] = datetime.now(timezone.utc).isoformat()
        st["default_exchange"] = settings.exchange
        st["paper_capital"] = settings.paper_capital
        st["trading_mode_env"] = settings.trading_mode
        return st

    @app.get("/api/exchanges")
    def api_exchanges():
        return {
            "exchanges": ["bithumb", "upbit"],
            "active_default": settings.exchange,
            "bithumb_fee": settings.bithumb_fee_rate,
            "upbit_fee": settings.upbit_fee_rate,
        }

    @app.get("/api/strategies")
    def api_strategies():
        return {"strategies": list(STRATEGY_REGISTRY.keys()) + ["adaptive_ensemble"]}

    @app.get("/api/equity")
    def api_equity(limit: int = 500):
        return {"equity": _read_equity(limit=limit)}

    @app.get("/api/trades")
    def api_trades(limit: int = 100):
        return {"trades": _read_trades(limit=limit)}

    @app.get("/api/weights")
    def api_weights():
        return {"weights": _read_weights(), "best_params": _read_best_params()}

    @app.get("/api/positions")
    def api_positions():
        bot = mgr.current_bot()
        if bot is None:
            return {"positions": []}
        out = []
        for mkt in bot.markets:
            pos = bot.executor.get_position(mkt)
            if pos is None:
                continue
            d = pos.to_dict()
            d["market"] = mkt
            # Attach current market price if reachable
            try:
                t = bot.exchange.get_ticker(mkt)
                px = t.get("trade_price") or 0.0
                d["current_price"] = px
                d["unrealised_pnl"] = (
                    (px - d["avg_price"]) * d["quantity"] if d["avg_price"] else 0.0
                )
            except Exception:
                d["current_price"] = None
                d["unrealised_pnl"] = None
            out.append(d)
        return {"positions": out}

    # ------------------------------------------------------------------
    # Live activity (logs) — lets the user *see* what the bot is doing
    # ------------------------------------------------------------------
    @app.get("/api/logs")
    def api_logs(limit: int = 100, since_seq: int = 0):
        from src.utils.log_buffer import LOG_BUFFER
        return {"logs": LOG_BUFFER.tail(limit=limit, since_seq=since_seq)}

    # ------------------------------------------------------------------
    # Analytics KPIs
    # ------------------------------------------------------------------
    @app.get("/api/analytics")
    def api_analytics():
        return compute_analytics()

    # ------------------------------------------------------------------
    # Chart data (OHLCV + common indicators)
    # ------------------------------------------------------------------
    @app.get("/api/chart")
    def api_chart(
        market: str = "KRW-BTC",
        timeframe: str = "1d",
        count: int = 200,
        exchange: Optional[str] = None,
    ):
        count = max(30, min(count, 500))
        try:
            ex = build_exchange(exchange)
            candles = ex.fetch_ohlcv(market, timeframe=timeframe, count=count)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"fetch failed: {exc}")
        df = candles_to_dataframe(candles)
        if df.empty:
            return {"market": market, "exchange": ex.name, "rows": [], "indicators": {}}

        rows = [
            {
                "ts": idx.isoformat(),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r["volume"]),
            }
            for idx, r in df.iterrows()
        ]
        return {
            "market": market,
            "exchange": ex.name,
            "timeframe": timeframe,
            "rows": rows,
            "indicators": _indicators_payload(df),
        }

    # ------------------------------------------------------------------
    # Current signals — every strategy's opinion explained
    # ------------------------------------------------------------------
    @app.get("/api/signals")
    def api_signals(
        market: str = "KRW-BTC",
        timeframe: str = "1d",
        count: int = 200,
        exchange: Optional[str] = None,
    ):
        try:
            ex = build_exchange(exchange)
            candles = ex.fetch_ohlcv(market, timeframe=timeframe, count=count)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"fetch failed: {exc}")
        df = candles_to_dataframe(candles)
        if df.empty:
            return {"market": market, "signals": []}

        # Pass the live bot's position (if any) so exit signals make sense.
        bot = mgr.current_bot()
        position = None
        if bot is not None:
            pos = bot.executor.get_position(market)
            if pos is not None:
                position = pos.to_dict()

        signals = _signals_for(df, position=position)
        last = df.iloc[-1]
        return {
            "market": market,
            "exchange": ex.name,
            "timeframe": timeframe,
            "as_of": df.index[-1].isoformat(),
            "last_close": float(last["close"]),
            "position": position,
            "signals": signals,
        }

    # ------------------------------------------------------------------
    # Watchlist — multiple markets at once
    # ------------------------------------------------------------------
    @app.get("/api/watchlist")
    def api_watchlist(markets: str = "KRW-BTC,KRW-ETH,KRW-XRP,KRW-SOL",
                      exchange: Optional[str] = None):
        try:
            ex = build_exchange(exchange)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"exchange init failed: {exc}")
        out = []
        for m in [s.strip().upper() for s in markets.split(",") if s.strip()]:
            try:
                t = ex.get_ticker(m)
                out.append({"market": m, "ticker": t, "error": None})
            except Exception as exc:
                out.append({"market": m, "ticker": None, "error": str(exc)})
        return {"exchange": ex.name, "markets": out}

    @app.get("/api/ticker/{market}")
    def api_ticker(market: str, exchange: Optional[str] = None):
        try:
            ex = build_exchange(exchange)
            tick = ex.get_ticker(market)
            return {"market": market, "exchange": ex.name, "ticker": tick}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"ticker failed: {exc}")

    # ------------------------------------------------------------------
    # Backtest runner — entirely in-process
    # ------------------------------------------------------------------
    @app.post("/api/backtest")
    def api_backtest(req: BacktestRequest):
        from src.backtesting import Backtester
        try:
            ex = build_exchange(req.exchange)
            candles = ex.fetch_ohlcv(req.market, timeframe=req.timeframe, count=req.count)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"fetch failed: {exc}")
        df = candles_to_dataframe(candles)
        if df.empty:
            raise HTTPException(status_code=400, detail="no data returned")
        try:
            strat = get_strategy(req.strategy)
            bt = Backtester(strategy=strat, starting_capital=req.capital)
            result = bt.run(df)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        # Downsample equity curve for transport
        eq = result.equity_curve
        step = max(1, len(eq) // 300)
        equity_points = [
            {"ts": str(ts), "equity": float(v)}
            for ts, v in list(zip(eq.index, eq.values))[::step]
        ]
        return {
            "market": req.market,
            "exchange": ex.name,
            "strategy": req.strategy,
            "timeframe": req.timeframe,
            "summary": {
                "starting_equity": result.starting_equity,
                "final_equity": result.final_equity,
                "total_return": result.total_return,
                "max_drawdown": result.max_drawdown,
                "sharpe_ratio": result.sharpe_ratio,
                "profit_factor": (
                    None if result.profit_factor in (float("inf"),) else result.profit_factor
                ),
                "win_rate": result.win_rate,
                "num_trades": result.num_trades,
            },
            "equity_curve": equity_points,
            "trades": [
                {
                    "ts": str(t.get("ts")),
                    "side": t.get("side"),
                    "price": t.get("price"),
                    "qty": t.get("qty"),
                    "reason": t.get("reason"),
                    "pnl": t.get("pnl"),
                }
                for t in result.trades[-200:]
            ],
        }

    # ------------------------------------------------------------------
    # Bot lifecycle
    # ------------------------------------------------------------------
    @app.post("/api/start")
    def api_start(req: StartRequest):
        try:
            status = mgr.start(
                mode=req.mode,
                markets=[m.upper() for m in req.markets],
                strategy=req.strategy,
                timeframe=req.timeframe,
                exchange=req.exchange,
            )
            return status.to_dict()
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"start failed: {exc}")

    @app.post("/api/stop")
    def api_stop():
        return mgr.stop().to_dict()

    # ------------------------------------------------------------------
    # WebSocket — 1 Hz push with equity tail, trades tail, logs, weights
    # ------------------------------------------------------------------
    @app.websocket("/ws")
    async def ws(ws: WebSocket):
        from src.utils.log_buffer import LOG_BUFFER
        await ws.accept()
        try:
            while True:
                payload = {
                    "type": "tick",
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "status": mgr.status().to_dict(),
                    "equity_tail": _read_equity(limit=50),
                    "trades_tail": _read_trades(limit=10),
                    "weights": _read_weights(),
                    "logs": LOG_BUFFER.tail(limit=30),
                }
                await ws.send_text(json.dumps(payload))
                await asyncio.sleep(1.0)
        except WebSocketDisconnect:
            return
        except Exception:  # pragma: no cover - runtime
            try:
                await ws.close()
            except Exception:
                pass

    # --------------------------------------------------------------
    # Static SPA (served last so API routes take priority)
    # --------------------------------------------------------------
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

        @app.get("/")
        def index():
            idx = STATIC_DIR / "index.html"
            if idx.exists():
                return FileResponse(str(idx))
            return JSONResponse({"message": "dashboard assets missing"}, status_code=404)

    return app
