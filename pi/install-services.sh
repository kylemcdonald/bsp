#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

sudo install -m 0644 "$SCRIPT_DIR/plotter/plotter.service" /etc/systemd/system/plotter.service
sudo install -m 0644 "$SCRIPT_DIR/camera/camera.service" /etc/systemd/system/camera.service
sudo install -m 0644 "$SCRIPT_DIR/button/button.service" /etc/systemd/system/button.service

sudo systemctl daemon-reload
sudo systemctl enable plotter.service camera.service button.service
sudo systemctl restart plotter.service camera.service button.service

systemctl --no-pager --full status plotter.service camera.service button.service
