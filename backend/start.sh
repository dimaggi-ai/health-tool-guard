#!/usr/bin/env bash
# Tool Guard Evaluation Server — starts on port 8092
# Requires: ollama running + gemma4:e4b pulled
# Optional: set PYTHON=/path/to/venv/bin/python to use a specific venv;
#           defaults to python3 from PATH.
set -e
cd "$(dirname "$0")"
PYTHON="${PYTHON:-python3}"
exec "$PYTHON" -m uvicorn main:app --host 0.0.0.0 --port 8092
