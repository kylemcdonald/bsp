#!/usr/bin/env bash
set -euo pipefail

APP_USER="${APP_USER:-ubuntu}"
REPO_DIR="${REPO_DIR:-/home/$APP_USER/bsp}"

sudo apt update
sudo apt install -y \
    python3 \
    python3-venv \
    python3-pip \
    python3-gpiozero \
    python3-opencv \
    python3-numpy \
    v4l-utils \
    avahi-daemon

if apt-cache show python3-lgpio >/dev/null 2>&1; then
    sudo apt install -y python3-lgpio
fi

sudo groupadd -f gpio
for group in dialout video gpio; do
    if getent group "$group" >/dev/null; then
        sudo usermod -aG "$group" "$APP_USER"
    fi
done

sudo tee /etc/udev/rules.d/99-bsp-gpio.rules >/dev/null <<'EOF'
SUBSYSTEM=="gpio", KERNEL=="gpiochip*", GROUP="gpio", MODE="0660"
KERNEL=="gpiomem", GROUP="gpio", MODE="0660"
EOF
sudo udevadm control --reload-rules
sudo udevadm trigger || true

sudo install -d -m 0755 /etc/sudoers.d
sudo tee /etc/sudoers.d/bsp-shutdown >/dev/null <<EOF
$APP_USER ALL=(root) NOPASSWD: /usr/sbin/shutdown -h now
EOF
sudo chmod 0440 /etc/sudoers.d/bsp-shutdown
sudo visudo -cf /etc/sudoers.d/bsp-shutdown

"$REPO_DIR/pi/setup-venv.sh"

echo "System dependencies installed."
echo "Log out and back in, or reboot, so group membership changes take effect."
