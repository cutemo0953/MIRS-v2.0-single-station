#!/bin/bash
# =============================================================================
# MIRS OTA Update Script
# =============================================================================
#
# Purpose: Manual OTA update operations for MIRS
# Platform: Raspberry Pi 5 (ARM64) / Docker
#
# Usage:
#   ./scripts/ota_update.sh check          # Check for updates
#   ./scripts/ota_update.sh update [tag]   # Apply update (optional specific tag)
#   ./scripts/ota_update.sh rollback       # Rollback to previous version
#   ./scripts/ota_update.sh status         # Show current status
#
# Version: 1.0
# Date: 2026-01-25
# Reference: DEV_SPEC_COMMERCIAL_APPLIANCE_v1.6 (P1-04)
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
DATA_DIR="${MIRS_DATA_DIR:-/var/lib/mirs}"
UPDATE_SERVER="${MIRS_UPDATE_SERVER:-https://updates.xirs.io}"
DOCKER_REGISTRY="${MIRS_DOCKER_REGISTRY:-ghcr.io/xirs}"
DOCKER_IMAGE="mirs-hub"

# Detect deployment type
detect_deployment() {
    if [ -f "/.dockerenv" ]; then
        echo "docker"
    elif [ -f "/app/mirs-hub" ]; then
        echo "binary"
    elif [ -f "$PROJECT_DIR/main.py" ]; then
        echo "source"
    else
        echo "unknown"
    fi
}

DEPLOYMENT_TYPE=$(detect_deployment)

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# =============================================================================
# Version Functions
# =============================================================================

get_current_version() {
    if [ -f "$DATA_DIR/version.json" ]; then
        cat "$DATA_DIR/version.json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('version', 'unknown'))" 2>/dev/null || echo "unknown"
    else
        echo "2.4.0"  # Default version
    fi
}

get_latest_version() {
    local channel="${1:-stable}"
    curl -s "$UPDATE_SERVER/api/v1/updates/$channel/latest?product=mirs-hub&platform=arm64" 2>/dev/null | \
        python3 -c "import sys,json; print(json.load(sys.stdin).get('version', 'unknown'))" 2>/dev/null || echo "unknown"
}

save_version() {
    local version="$1"
    mkdir -p "$DATA_DIR"
    cat > "$DATA_DIR/version.json" << EOF
{
    "version": "$version",
    "build_date": "$(date -Iseconds)",
    "update_method": "$DEPLOYMENT_TYPE"
}
EOF
}

# =============================================================================
# Docker Operations
# =============================================================================

docker_get_current_tag() {
    docker inspect --format '{{.Config.Image}}' $(docker ps -q -f "name=mirs" | head -1) 2>/dev/null | \
        sed 's/.*://' || echo "unknown"
}

docker_pull() {
    local tag="$1"
    log_info "Pulling image: $DOCKER_REGISTRY/$DOCKER_IMAGE:$tag"
    docker pull "$DOCKER_REGISTRY/$DOCKER_IMAGE:$tag"
}

docker_update() {
    local new_tag="${1:-latest}"
    local current_tag=$(docker_get_current_tag)

    log_info "Current tag: $current_tag"
    log_info "New tag: $new_tag"

    # Save rollback info
    mkdir -p "$DATA_DIR"
    echo "$current_tag" > "$DATA_DIR/rollback_tag"

    # Pull new image
    docker_pull "$new_tag"

    # If using docker-compose
    if [ -f "$PROJECT_DIR/docker-compose.yml" ]; then
        log_info "Restarting with docker-compose..."
        cd "$PROJECT_DIR"
        docker-compose pull
        docker-compose up -d
    else
        log_warn "Manual container restart required"
        log_info "Run: docker stop <container> && docker run ... $DOCKER_REGISTRY/$DOCKER_IMAGE:$new_tag"
    fi

    save_version "$new_tag"
    log_success "Update complete"
}

docker_rollback() {
    if [ ! -f "$DATA_DIR/rollback_tag" ]; then
        log_error "No rollback information available"
        exit 1
    fi

    local rollback_tag=$(cat "$DATA_DIR/rollback_tag")
    log_info "Rolling back to: $rollback_tag"

    docker_update "$rollback_tag"
    rm -f "$DATA_DIR/rollback_tag"
}

# =============================================================================
# Binary Operations
# =============================================================================

binary_backup() {
    if [ -f "/app/mirs-hub" ]; then
        log_info "Backing up current binary..."
        cp /app/mirs-hub /app/mirs-hub.backup
        get_current_version > "$DATA_DIR/rollback_version"
    fi
}

binary_download() {
    local url="$1"
    local dest="/tmp/mirs-hub.new"

    log_info "Downloading update from $url..."
    curl -L -o "$dest" "$url"

    if [ -f "$dest" ]; then
        chmod +x "$dest"
        echo "$dest"
    else
        log_error "Download failed"
        exit 1
    fi
}

binary_update() {
    local new_binary="$1"

    binary_backup

    log_info "Installing new binary..."
    mv "$new_binary" /app/mirs-hub
    chmod +x /app/mirs-hub

    # Signal systemd to restart
    if systemctl is-active mirs.service &>/dev/null; then
        log_info "Restarting mirs service..."
        sudo systemctl restart mirs.service
    else
        log_warn "Manual restart required"
    fi

    log_success "Update complete"
}

binary_rollback() {
    if [ ! -f "/app/mirs-hub.backup" ]; then
        log_error "No backup binary available"
        exit 1
    fi

    log_info "Rolling back to previous binary..."
    cp /app/mirs-hub.backup /app/mirs-hub

    if systemctl is-active mirs.service &>/dev/null; then
        sudo systemctl restart mirs.service
    fi

    log_success "Rollback complete"
}

# =============================================================================
# Health Check
# =============================================================================

wait_for_healthy() {
    local timeout="${1:-60}"
    local url="http://localhost:8000/api/health"

    log_info "Waiting for service to be healthy..."

    for i in $(seq 1 $timeout); do
        if curl -s "$url" | grep -q "ok\|healthy"; then
            log_success "Service is healthy"
            return 0
        fi
        sleep 1
    done

    log_error "Health check timeout"
    return 1
}

# =============================================================================
# Commands
# =============================================================================

cmd_status() {
    echo ""
    echo "========================================"
    echo "  MIRS OTA Status"
    echo "========================================"
    echo ""
    echo "Deployment Type: $DEPLOYMENT_TYPE"
    echo "Current Version: $(get_current_version)"

    if [ "$DEPLOYMENT_TYPE" = "docker" ]; then
        echo "Docker Tag:      $(docker_get_current_tag)"
    fi

    echo "Data Directory:  $DATA_DIR"
    echo "Update Server:   $UPDATE_SERVER"
    echo ""

    # Check for rollback availability
    if [ -f "$DATA_DIR/rollback_tag" ] || [ -f "/app/mirs-hub.backup" ]; then
        echo "Rollback:        Available"
    else
        echo "Rollback:        Not available"
    fi
    echo ""
}

cmd_check() {
    local channel="${1:-stable}"

    echo ""
    log_info "Checking for updates (channel: $channel)..."
    echo ""

    local current=$(get_current_version)
    local latest=$(get_latest_version "$channel")

    echo "Current Version: $current"
    echo "Latest Version:  $latest"
    echo ""

    if [ "$current" = "$latest" ]; then
        log_success "You are running the latest version"
    elif [ "$latest" = "unknown" ]; then
        log_warn "Could not check for updates (server unreachable)"
    else
        log_info "Update available: $current -> $latest"
        echo ""
        echo "To update, run: $0 update $latest"
    fi
    echo ""
}

cmd_update() {
    local version="$1"

    echo ""
    log_info "Starting update..."
    echo ""

    case "$DEPLOYMENT_TYPE" in
        docker)
            docker_update "${version:-latest}"
            ;;
        binary)
            if [ -z "$version" ]; then
                log_error "Version or download URL required for binary update"
                exit 1
            fi
            local new_binary=$(binary_download "$UPDATE_SERVER/downloads/mirs-hub-$version-arm64")
            binary_update "$new_binary"
            ;;
        source)
            log_info "Source deployment - pulling latest code..."
            cd "$PROJECT_DIR"
            git pull
            log_info "Restarting service..."
            # Try different restart methods
            if systemctl is-active mirs.service &>/dev/null; then
                sudo systemctl restart mirs.service
            elif [ -f "$PROJECT_DIR/start.sh" ]; then
                pkill -f "uvicorn main:app" || true
                sleep 2
                nohup "$PROJECT_DIR/start.sh" &
            fi
            ;;
        *)
            log_error "Unknown deployment type: $DEPLOYMENT_TYPE"
            exit 1
            ;;
    esac

    # Wait for healthy
    sleep 5
    if wait_for_healthy 60; then
        log_success "Update successful!"
    else
        log_error "Update may have failed - service not healthy"
        log_info "Consider running: $0 rollback"
    fi
}

cmd_rollback() {
    echo ""
    log_info "Starting rollback..."
    echo ""

    case "$DEPLOYMENT_TYPE" in
        docker)
            docker_rollback
            ;;
        binary)
            binary_rollback
            ;;
        source)
            log_info "Source deployment - use git to rollback"
            cd "$PROJECT_DIR"
            git log --oneline -5
            echo ""
            log_info "To rollback: git checkout <commit>"
            ;;
        *)
            log_error "Unknown deployment type"
            exit 1
            ;;
    esac

    if wait_for_healthy 60; then
        log_success "Rollback successful!"
    else
        log_error "Rollback may have failed"
    fi
}

# =============================================================================
# Main
# =============================================================================

show_help() {
    echo "MIRS OTA Update Script"
    echo ""
    echo "Usage: $0 <command> [options]"
    echo ""
    echo "Commands:"
    echo "  status              Show current version and OTA status"
    echo "  check [channel]     Check for available updates"
    echo "  update [version]    Apply update"
    echo "  rollback            Rollback to previous version"
    echo "  help                Show this help"
    echo ""
    echo "Channels: stable, beta, dev"
    echo ""
    echo "Examples:"
    echo "  $0 status"
    echo "  $0 check"
    echo "  $0 check beta"
    echo "  $0 update"
    echo "  $0 update 2.5.0"
    echo "  $0 rollback"
}

main() {
    case "${1:-}" in
        status)
            cmd_status
            ;;
        check)
            cmd_check "$2"
            ;;
        update)
            cmd_update "$2"
            ;;
        rollback)
            cmd_rollback
            ;;
        help|--help|-h)
            show_help
            ;;
        "")
            show_help
            ;;
        *)
            log_error "Unknown command: $1"
            echo ""
            show_help
            exit 1
            ;;
    esac
}

main "$@"
