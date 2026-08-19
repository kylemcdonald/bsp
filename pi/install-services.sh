#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

sudo install -m 0644 "$SCRIPT_DIR/runpod/bsp-runpod.service" /etc/systemd/system/bsp-runpod.service
sudo install -m 0644 "$SCRIPT_DIR/plotter/plotter.service" /etc/systemd/system/plotter.service
sudo install -m 0644 "$SCRIPT_DIR/camera/camera.service" /etc/systemd/system/camera.service
sudo install -m 0644 "$SCRIPT_DIR/button/button.service" /etc/systemd/system/button.service

sudo systemctl daemon-reload
sudo systemctl enable bsp-runpod.service plotter.service camera.service button.service
sudo systemctl restart bsp-runpod.service
sudo systemctl restart plotter.service camera.service button.service

systemctl --no-pager --full status bsp-runpod.service plotter.service camera.service button.service
