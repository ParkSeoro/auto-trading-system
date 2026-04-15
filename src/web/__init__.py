"""Web dashboard layer (FastAPI + WebSocket + static SPA).

See :func:`src.web.app.create_app` for the entry point used by
``scripts/run_web.py``.
"""
from src.web.app import create_app  # noqa: F401
