#!/usr/bin/env bash
set -euo pipefail

unit_name="bsp-restart-services-$(date +%s)-$$"

/usr/bin/systemd-run \
    --unit="$unit_name" \
    --description=BSP-restart-services-from-button-hold \
    --on-active=1s \
    /usr/bin/systemctl restart plotter.service camera.service button.service
