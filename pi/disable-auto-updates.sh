#!/usr/bin/env bash
set -euo pipefail

if [ "${EUID}" -ne 0 ]; then
  echo "Run with sudo: sudo bash $0" >&2
  exit 1
fi

echo "Disabling APT periodic update and upgrade jobs..."

cat >/etc/apt/apt.conf.d/99disable-auto-updates <<'EOF'
APT::Periodic::Enable "0";
APT::Periodic::Update-Package-Lists "0";
APT::Periodic::Download-Upgradeable-Packages "0";
APT::Periodic::AutocleanInterval "0";
APT::Periodic::Unattended-Upgrade "0";
Unattended-Upgrade::Automatic-Reboot "false";
EOF

apt_units=(
  apt-daily.timer
  apt-daily-upgrade.timer
  apt-daily.service
  apt-daily-upgrade.service
  unattended-upgrades.service
)

for unit in "${apt_units[@]}"; do
  if systemctl list-unit-files "$unit" --no-legend 2>/dev/null | grep -q .; then
    systemctl disable --now "$unit" 2>/dev/null || true
    systemctl mask "$unit" 2>/dev/null || true
  fi
done

echo "Disabling PackageKit background package activity, if installed..."

packagekit_units=(
  packagekit.service
  packagekit-offline-update.service
)

for unit in "${packagekit_units[@]}"; do
  if systemctl list-unit-files "$unit" --no-legend 2>/dev/null | grep -q .; then
    systemctl disable --now "$unit" 2>/dev/null || true
    systemctl mask "$unit" 2>/dev/null || true
  fi
done

echo "Disabling snapd automatic refresh/update activity, if installed..."

snap_units=(
  snapd.service
  snapd.socket
  snapd.seeded.service
  snapd.snap-repair.timer
  snapd.snap-repair.service
  snapd.autoimport.service
  snapd.recovery-chooser-trigger.service
)

for unit in "${snap_units[@]}"; do
  if systemctl list-unit-files "$unit" --no-legend 2>/dev/null | grep -q .; then
    systemctl disable --now "$unit" 2>/dev/null || true
    systemctl mask "$unit" 2>/dev/null || true
  fi
done

if command -v snap >/dev/null 2>&1; then
  # This is best-effort only; masking snapd above is what prevents background refreshes.
  snap set system refresh.metered=hold 2>/dev/null || true
fi

systemctl daemon-reload

echo
echo "Automatic update mechanisms disabled."
echo "Manual APT upgrades still work after unmasking the relevant units only if needed:"
echo "  sudo apt update"
echo "  sudo apt upgrade"
echo
echo "Masked update-related units:"
systemctl list-unit-files --state=masked --no-pager | grep -E 'apt-daily|unattended|packagekit|snapd' || true
