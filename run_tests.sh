#!/usr/bin/env bash
cd "$(dirname "$0")"
[ ! -x ".venv/bin/python" ] && { echo "install.sh 를 먼저 실행하세요."; exit 1; }
.venv/bin/python -m pytest -v
