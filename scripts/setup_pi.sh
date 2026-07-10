#!/usr/bin/env bash
# PiGauge Pi provisioning (Raspberry Pi OS Lite, Bookworm).
# Review docs/HARDWARE.md before running. Idempotent-ish; read before trusting.
set -euo pipefail

CONFIG=/boot/firmware/config.txt

echo "== apt packages =="
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv git can-utils i2c-tools

echo "== interface overlays (verify oscillator/int pin against YOUR HAT) =="
grep -q '^dtparam=spi=on' $CONFIG || echo 'dtparam=spi=on' | sudo tee -a $CONFIG
grep -q '^dtparam=i2c_arm=on' $CONFIG || echo 'dtparam=i2c_arm=on' | sudo tee -a $CONFIG
grep -q 'mcp2515-can0' $CONFIG || echo 'dtoverlay=mcp2515-can0,oscillator=8000000,interrupt=25' | sudo tee -a $CONFIG
grep -q 'spi1-2cs' $CONFIG || echo 'dtoverlay=spi1-2cs' | sudo tee -a $CONFIG

echo "== python env =="
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/pip install -e .[vehicle,pi]

echo "== systemd =="
sudo cp systemd/pigauge.service /etc/systemd/system/
sudo systemctl daemon-reload

echo
echo "Done. Reboot to apply overlays, then:"
echo "  sudo ip link set can0 up type can bitrate 500000   # CAN vehicles"
echo "  sudo systemctl enable --now pigauge"
echo
echo "SD card protection (recommended once stable):"
echo "  sudo raspi-config  ->  Performance Options  ->  Overlay File System"
echo "  (config writes from the web UI then require the data partition rw"
echo "   workflow described in docs/HARDWARE.md)"
