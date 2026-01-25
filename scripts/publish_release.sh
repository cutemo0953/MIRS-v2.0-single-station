#!/bin/bash
# =============================================================================
# MIRS Release Publishing Script
# =============================================================================
#
# Purpose: Build and publish a new MIRS release to the Update Server
# Usage:
#   ./scripts/publish_release.sh <version> [channel] [server_url]
#
# Examples:
#   ./scripts/publish_release.sh 2.5.0
#   ./scripts/publish_release.sh 2.5.0-beta beta
#   ./scripts/publish_release.sh 2.5.0 stable https://updates.example.com
#
# Version: 1.0
# Date: 2026-01-25
# =============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DIST_DIR="$PROJECT_DIR/dist"

VERSION="${1:-}"
CHANNEL="${2:-stable}"
UPDATE_SERVER="${3:-http://localhost:8080}"
ADMIN_KEY="${UPDATE_SERVER_ADMIN_KEY:-dev-admin-key}"

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# =============================================================================
# Validation
# =============================================================================

if [ -z "$VERSION" ]; then
    echo "Usage: $0 <version> [channel] [server_url]"
    echo ""
    echo "Arguments:"
    echo "  version     Version number (e.g., 2.5.0)"
    echo "  channel     Release channel: stable, beta, dev (default: stable)"
    echo "  server_url  Update server URL (default: http://localhost:8080)"
    echo ""
    echo "Environment:"
    echo "  UPDATE_SERVER_ADMIN_KEY  Admin API key"
    exit 1
fi

# =============================================================================
# Build
# =============================================================================

build_binary() {
    log_info "Building MIRS binary for ARM64..."

    cd "$PROJECT_DIR"

    # Check if we need to build
    if [ ! -f "$DIST_DIR/mirs-hub" ]; then
        log_info "Binary not found, building..."

        # Use Docker if available
        if command -v docker &> /dev/null && docker info &> /dev/null; then
            ./scripts/build_protected.sh
        else
            log_error "Docker not available. Build on RPi or install Docker."
            exit 1
        fi
    else
        log_info "Using existing binary: $DIST_DIR/mirs-hub"
    fi

    if [ ! -f "$DIST_DIR/mirs-hub" ]; then
        log_error "Build failed - binary not found"
        exit 1
    fi

    log_success "Binary ready"
}

# =============================================================================
# Publish
# =============================================================================

publish_release() {
    log_info "Publishing release $VERSION to $UPDATE_SERVER (channel: $CHANNEL)..."

    # 1. Create release record
    log_info "Creating release record..."

    RELEASE_NOTES="MIRS Hub v$VERSION"

    RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$UPDATE_SERVER/api/v1/admin/releases" \
        -H "X-API-Key: $ADMIN_KEY" \
        -H "Content-Type: application/json" \
        -d "{
            \"version\": \"$VERSION\",
            \"channel\": \"$CHANNEL\",
            \"release_notes\": \"$RELEASE_NOTES\"
        }")

    HTTP_CODE=$(echo "$RESPONSE" | tail -1)
    BODY=$(echo "$RESPONSE" | sed '$d')

    if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "409" ]; then
        log_success "Release record created (or already exists)"
    else
        log_error "Failed to create release: $BODY"
        exit 1
    fi

    # 2. Upload binary
    log_info "Uploading binary..."

    RESPONSE=$(curl -s -w "\n%{http_code}" -X POST \
        "$UPDATE_SERVER/api/v1/admin/releases/$VERSION/upload?channel=$CHANNEL" \
        -H "X-API-Key: $ADMIN_KEY" \
        -F "file=@$DIST_DIR/mirs-hub")

    HTTP_CODE=$(echo "$RESPONSE" | tail -1)
    BODY=$(echo "$RESPONSE" | sed '$d')

    if [ "$HTTP_CODE" = "200" ]; then
        log_success "Binary uploaded"
        echo "$BODY" | python3 -m json.tool 2>/dev/null || echo "$BODY"
    else
        log_error "Failed to upload binary: $BODY"
        exit 1
    fi

    # 3. Verify
    log_info "Verifying release..."

    RESPONSE=$(curl -s "$UPDATE_SERVER/api/v1/updates/$CHANNEL/latest?current_version=0.0.0")
    LATEST=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('version',''))" 2>/dev/null)

    if [ "$LATEST" = "$VERSION" ]; then
        log_success "Release $VERSION is now available on $CHANNEL channel"
    else
        log_error "Verification failed - latest version is $LATEST"
        exit 1
    fi
}

# =============================================================================
# Main
# =============================================================================

main() {
    echo ""
    echo "========================================"
    echo "  MIRS Release Publisher"
    echo "========================================"
    echo ""
    echo "Version:  $VERSION"
    echo "Channel:  $CHANNEL"
    echo "Server:   $UPDATE_SERVER"
    echo ""

    # Build if needed
    build_binary

    # Publish
    publish_release

    echo ""
    log_success "=== Release $VERSION published successfully! ==="
    echo ""
    echo "Clients can update with:"
    echo "  ./scripts/ota_update.sh check"
    echo "  ./scripts/ota_update.sh update"
    echo ""
}

main
