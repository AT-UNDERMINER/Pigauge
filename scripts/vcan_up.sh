#!/usr/bin/env bash
# Create a virtual CAN interface for testing (Linux dev machine or Pi).
set -euo pipefail
sudo modprobe vcan
sudo ip link add dev vcan0 type vcan 2>/dev/null || true
sudo ip link set up vcan0
echo "vcan0 up"
