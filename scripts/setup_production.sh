#!/bin/bash
# =============================================================================
# MIRS Production Setup Script
# =============================================================================
#
# Purpose: Convert RPi from development mode (Python) to production mode (Binary)
#
# What it does:
# 1. Creates /app directory structure for atomic updates
# 2. Installs compiled binary
# 3. Updates systemd service to use binary
# 4. Enables OTA auto-update
#
# Usage:
#   sudo ./scripts/setup_production.sh
#
# Version: 1.0
# Date: 2026-01-26
# =============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

# Check root
if [ "$EUID" -ne 0 ]; then
    log_error "Please run as root: sudo $0"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BINARY_SOURCE="$PROJECT_DIR/dist/mirs-server"

# =============================================================================
# Configuration
# =============================================================================

APP_DIR="/app"
VERSIONS_DIR="$APP_DIR/versions"
DATA_DIR="/var/lib/mirs"
CONFIG_DIR="/etc/mirs"
CURRENT_VERSION=$(grep -o 'CURRENT_VERSION = "[^"]*"' "$PROJECT_DIR/services/ota_service.py" 2>/dev/null | cut -d'"' -f2 || echo "2.4.0")

log_info "Setting up MIRS production environment"
log_info "Version: $CURRENT_VERSION"

# =============================================================================
# Step 1: Create directory structure
# =============================================================================

log_info "Creating directory structure..."

mkdir -p "$APP_DIR"
mkdir -p "$VERSIONS_DIR/$CURRENT_VERSION"
mkdir -p "$DATA_DIR/ota/cache"
mkdir -p "$DATA_DIR/ota/state"
mkdir -p "$CONFIG_DIR"

# =============================================================================
# Step 2: Install binary
# =============================================================================

if [ ! -f "$BINARY_SOURCE" ]; then
    log_error "Binary not found at $BINARY_SOURCE"
    log_info "Please run ./scripts/build_on_rpi.sh first"
    exit 1
fi

log_info "Installing binary to $VERSIONS_DIR/$CURRENT_VERSION/"

cp "$BINARY_SOURCE" "$VERSIONS_DIR/$CURRENT_VERSION/mirs-server"
chmod +x "$VERSIONS_DIR/$CURRENT_VERSION/mirs-server"

# Create symlink
ln -sf "$VERSIONS_DIR/$CURRENT_VERSION/mirs-server" "$APP_DIR/mirs-server"

log_success "Binary installed: $(ls -la $APP_DIR/mirs-server)"

# =============================================================================
# Step 3: Copy data files
# =============================================================================

log_info "Setting up data directory..."

# Copy existing database if exists
if [ -f "$PROJECT_DIR/data/medical_inventory.db" ]; then
    cp "$PROJECT_DIR/data/medical_inventory.db" "$DATA_DIR/"
    log_success "Database copied to $DATA_DIR/"
fi

# Ensure public key exists
if [ -f "$CONFIG_DIR/ota_pubkey.pub" ]; then
    log_success "Public key found at $CONFIG_DIR/ota_pubkey.pub"
else
    log_warn "Public key not found. OTA signature verification will be skipped."
    log_info "Copy public key: scp ota_pubkey.pub root@rpi:/etc/mirs/"
fi

# =============================================================================
# Step 4: Create systemd service
# =============================================================================

log_info "Creating systemd service..."

cat > /etc/systemd/system/mirs.service << 'EOF'
[Unit]
Description=Medical Inventory Resilience System (MIRS) - Production
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/app

# Production binary
ExecStart=/app/mirs-server

# Environment
Environment=MIRS_PORT=8000
Environment=MIRS_DB_PATH=/var/lib/mirs/medical_inventory.db
Environment=MIRS_DATA_DIR=/var/lib/mirs
Environment=MIRS_APP_DIR=/app

# OTA Configuration
Environment=MIRS_OTA_AUTO_UPDATE=true
Environment=MIRS_OTA_REQUIRE_SIGNATURE=true
Environment=MIRS_GITHUB_REPO=cutemo0953/xirs-releases
Environment=MIRS_OTA_SCHEDULER_ENABLED=true
Environment=MIRS_OTA_WINDOW_START=02:00
Environment=MIRS_OTA_WINDOW_END=05:00

# Restart policy
Restart=always
RestartSec=10

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=mirs

[Install]
WantedBy=multi-user.target
EOF

log_success "Systemd service created"

# =============================================================================
# Step 5: Enable and start service
# =============================================================================

log_info "Enabling and starting service..."

systemctl daemon-reload
systemctl enable mirs
systemctl restart mirs

sleep 3

if systemctl is-active --quiet mirs; then
    log_success "MIRS service is running"
else
    log_error "MIRS service failed to start"
    journalctl -u mirs -n 20 --no-pager
    exit 1
fi

# =============================================================================
# Step 6: Verify
# =============================================================================

log_info "Verifying installation..."

sleep 2

HEALTH=$(curl -s http://localhost:8000/api/health 2>/dev/null || echo "FAILED")
if echo "$HEALTH" | grep -q "healthy"; then
    log_success "Health check passed"
else
    log_warn "Health check: $HEALTH"
fi

OTA_STATUS=$(curl -s http://localhost:8000/api/ota/status 2>/dev/null || echo "FAILED")
log_info "OTA Status: $OTA_STATUS"

# =============================================================================
# Done
# =============================================================================

echo ""
echo "========================================"
echo "  MIRS Production Setup Complete"
echo "========================================"
echo ""
echo "Binary:     $APP_DIR/mirs-server -> $VERSIONS_DIR/$CURRENT_VERSION/mirs-server"
echo "Database:   $DATA_DIR/medical_inventory.db"
echo "Config:     $CONFIG_DIR/"
echo "Service:    systemctl status mirs"
echo ""
echo "OTA Auto-Update: ENABLED"
echo "Update Window:   02:00 - 05:00"
echo ""
echo "Commands:"
echo "  curl http://localhost:8000/api/health      # Health check"
echo "  curl http://localhost:8000/api/ota/check   # Check for updates"
echo "  journalctl -u mirs -f                      # View logs"
echo ""
log_success "Setup complete!"
