"""Launch the web dashboard.

Usage::

    python -m scripts.run_web --host 0.0.0.0 --port 8787
"""
from __future__ import annotations

import argparse
import sys

from src.utils.logger import get_logger

log = get_logger("run_web")


def main() -> int:
    parser = argparse.ArgumentParser(description="Crypto auto-trading web dashboard")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Bind host (0.0.0.0 to expose on LAN)")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--reload", action="store_true",
                        help="uvicorn auto-reload (development only)")
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError:
        print("[ERROR] fastapi/uvicorn missing.")
        print("  Windows: run 'run_web.bat' (auto-installs deps), or re-run install.bat")
        print("  macOS/Linux: ./run_web.sh  (auto-installs deps)")
        print("  Manual:  .venv\\Scripts\\python.exe -m pip install -r requirements.txt  (Windows)")
        print("           .venv/bin/python    -m pip install -r requirements.txt  (Unix)")
        return 1

    from src.web import create_app  # lazy import so --help works without deps
    app = create_app()
    log.info("Dashboard at http://%s:%d", args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
