#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$REPO_DIR/.venv"

if ! python3 -m venv "$VENV_DIR" --system-site-packages; then
    rm -rf "$VENV_DIR"
    echo "Failed to create venv. Install python3-venv, then rerun this script." >&2
    exit 1
fi
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$REPO_DIR/pi/requirements-pi.txt"

"$VENV_DIR/bin/python" - <<'PY'
import cv2
import flask
import gpiozero
import numpy
import requests
import serial
import waitress

print("Pi Python environment OK")
PY
