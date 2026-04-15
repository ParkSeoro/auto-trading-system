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
- ``POST /api/start``          start the bot (paper/live)
- ``POST /api/stop``           stop the bot
- ``GET  /api/ticker/{mkt}``   instant ticker snapshot
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

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config.settings import settings
from src.exchanges import build_exchange
from src.strategies import STRATEGY_REGISTRY
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
# App factory
# ----------------------------------------------------------------------
def create_app(manager: Optional[BotManager] = None) -> FastAPI:
    mgr = manager or BotManager()
    app = FastAPI(
        title="Crypto Auto-Trading Dashboard",
        description="Bithumb / Upbit 자동매매 대시보드 · AI 자가진화 엔진 지원",
        version="1.0",
    )

    @app.get("/api/status")
    def api_status():
        st = mgr.status().to_dict()
        st["server_time"] = datetime.now(timezone.utc).isoformat()
        st["default_exchange"] = settings.exchange
        st["paper_capital"] = settings.paper_capital
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
        names = list(STRATEGY_REGISTRY.keys()) + ["adaptive_ensemble"]
        return {"strategies": names}

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
            out.append(d)
        return {"positions": out}

    @app.get("/api/ticker/{market}")
    def api_ticker(market: str, exchange: Optional[str] = None):
        try:
            ex = build_exchange(exchange)
            tick = ex.get_ticker(market)
            return {"market": market, "exchange": ex.name, "ticker": tick}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"ticker failed: {exc}")

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

    # --------------------------------------------------------------
    # WebSocket — 1 Hz push with equity tail & status
    # --------------------------------------------------------------
    @app.websocket("/ws")
    async def ws(ws: WebSocket):
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
