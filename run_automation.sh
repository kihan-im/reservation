#!/usr/bin/env bash
cd "$(dirname "$0")"
if [ -d "venv" ]; then
    PYTHON_BIN="venv/bin/python"
elif [ -f "/tmp/cip_venv/bin/python" ]; then
    PYTHON_BIN="/tmp/cip_venv/bin/python"
else
    PYTHON_BIN="python3"
fi
"$PYTHON_BIN" main.py "$@"
