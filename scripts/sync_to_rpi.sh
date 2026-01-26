#!/bin/bash
# Sync MIRS files to Raspberry Pi
# Usage: ./scripts/sync_to_rpi.sh [host]
#
# Examples:
#   ./scripts/sync_to_rpi.sh                    # Uses default mirs@raspberrypi.local
#   ./scripts/sync_to_rpi.sh mirs@192.168.1.100

set -e

HOST="${1:-dno@10.0.0.1}"
REMOTE_DIR="/home/dno/MIRS-v2.0-single-station"

echo "========================================"
echo "Syncing MIRS to $HOST"
echo "========================================"

# OTA Services
echo ""
echo "[1/4] Syncing OTA services..."
scp services/ota_safety.py \
    services/ota_security.py \
    services/ota_scheduler.py \
    services/ota_service.py \
    "$HOST:$REMOTE_DIR/services/"

# OTA Routes
echo ""
echo "[2/4] Syncing OTA routes..."
scp routes/ota.py "$HOST:$REMOTE_DIR/routes/"

# Main app
echo ""
echo "[3/4] Syncing main.py..."
scp main.py "$HOST:$REMOTE_DIR/"

# Scripts
echo ""
echo "[4/5] Syncing scripts..."
scp scripts/build_on_rpi.sh \
    scripts/create_release.sh \
    "$HOST:$REMOTE_DIR/scripts/"

# Tests
echo ""
echo "[5/5] Syncing tests..."
ssh "$HOST" "mkdir -p $REMOTE_DIR/tests"
scp tests/test_ota_scheduler.py "$HOST:$REMOTE_DIR/tests/"

echo ""
echo "========================================"
echo "Sync complete!"
echo "========================================"
echo ""
echo "To test on RPi:"
echo "  ssh $HOST"
echo "  cd $REMOTE_DIR"
echo "  python tests/test_ota_scheduler.py"
echo ""
echo "To restart MIRS:"
echo "  sudo systemctl restart mirs"
