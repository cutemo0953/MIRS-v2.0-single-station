#!/bin/bash
#
# MIRS Auto-Update Script (Source-based)
#
# This script checks for updates from GitHub and applies them automatically.
# Designed for RPi deployments running from source code.
#
# Usage:
#   ./scripts/auto-update.sh              # Check and update
#   ./scripts/auto-update.sh --check      # Check only, don't apply
#   ./scripts/auto-update.sh --force      # Force update even if no changes
#
# Cron example (check every hour, update at 3am):
#   0 * * * * /opt/mirs/scripts/auto-update.sh --check >> /var/log/mirs-update.log 2>&1
#   0 3 * * * /opt/mirs/scripts/auto-update.sh >> /var/log/mirs-update.log 2>&1
#
# Version: 1.0
# Date: 2026-01-26
#

set -e

# Configuration - Auto-detect directory if not set
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIRS_DIR="${MIRS_DIR:-$(dirname "$SCRIPT_DIR")}"
MIRS_SERVICE="${MIRS_SERVICE:-mirs}"
MIRS_BRANCH="${MIRS_BRANCH:-main}"
MIRS_REMOTE="${MIRS_REMOTE:-origin}"
LOG_FILE="${MIRS_LOG_FILE:-/var/log/mirs-update.log}"
LOCK_FILE="/var/lock/mirs-update.lock"

# Safety: Update window (default: 02:00 - 05:00)
UPDATE_WINDOW_START="${MIRS_UPDATE_WINDOW_START:-02:00}"
UPDATE_WINDOW_END="${MIRS_UPDATE_WINDOW_END:-05:00}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

log_error() {
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1${NC}" >&2
}

log_success() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')] $1${NC}"
}

log_warn() {
    echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: $1${NC}"
}

# Check if we're in the update window
in_update_window() {
    local current_time=$(date +%H:%M)
    if [[ "$current_time" > "$UPDATE_WINDOW_START" && "$current_time" < "$UPDATE_WINDOW_END" ]]; then
        return 0
    fi
    return 1
}

# Check if MIRS has active cases (safety check)
has_active_cases() {
    local response
    response=$(curl -s "http://localhost:8000/api/anesthesia/cases?status=IN_PROGRESS" 2>/dev/null || echo '{"count":0}')
    local count=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('count',0))" 2>/dev/null || echo "0")
    if [[ "$count" -gt 0 ]]; then
        return 0
    fi
    return 1
}

# Acquire lock
acquire_lock() {
    exec 200>"$LOCK_FILE"
    if ! flock -n 200; then
        log_error "Another update process is running"
        exit 1
    fi
}

# Check for updates
check_updates() {
    log "Checking for updates..."

    cd "$MIRS_DIR"

    # Fetch latest
    git fetch "$MIRS_REMOTE" "$MIRS_BRANCH" --quiet

    # Compare
    local local_commit=$(git rev-parse HEAD)
    local remote_commit=$(git rev-parse "$MIRS_REMOTE/$MIRS_BRANCH")

    if [[ "$local_commit" == "$remote_commit" ]]; then
        log "Already up to date (${local_commit:0:7})"
        return 1
    fi

    # Show what's new
    local new_commits=$(git log --oneline HEAD.."$MIRS_REMOTE/$MIRS_BRANCH" | wc -l)
    log "Update available: $new_commits new commit(s)"
    git log --oneline HEAD.."$MIRS_REMOTE/$MIRS_BRANCH" | head -5

    return 0
}

# Apply update
apply_update() {
    log "Applying update..."

    cd "$MIRS_DIR"

    # Create backup tag
    local backup_tag="backup-$(date +%Y%m%d-%H%M%S)"
    git tag "$backup_tag" HEAD
    log "Created backup tag: $backup_tag"

    # Pull changes
    git pull "$MIRS_REMOTE" "$MIRS_BRANCH" --ff-only

    if [[ $? -ne 0 ]]; then
        log_error "Git pull failed, attempting to recover..."
        git reset --hard "$backup_tag"
        return 1
    fi

    local new_commit=$(git rev-parse --short HEAD)
    log_success "Updated to $new_commit"

    return 0
}

# Restart service
restart_service() {
    log "Restarting MIRS service..."

    if systemctl is-active --quiet "$MIRS_SERVICE"; then
        sudo systemctl restart "$MIRS_SERVICE"
        sleep 5

        if systemctl is-active --quiet "$MIRS_SERVICE"; then
            log_success "Service restarted successfully"
            return 0
        else
            log_error "Service failed to start"
            return 1
        fi
    else
        log_warn "Service not running, skipping restart"
        return 0
    fi
}

# Health check
health_check() {
    log "Running health check..."

    local max_attempts=10
    local attempt=1

    while [[ $attempt -le $max_attempts ]]; do
        local response=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:8000/api/dr/health" 2>/dev/null || echo "000")

        if [[ "$response" == "200" ]]; then
            log_success "Health check passed"
            return 0
        fi

        log "Health check attempt $attempt/$max_attempts (HTTP $response)"
        sleep 3
        ((attempt++))
    done

    log_error "Health check failed after $max_attempts attempts"
    return 1
}

# Rollback
rollback() {
    log_warn "Rolling back to previous version..."

    cd "$MIRS_DIR"

    # Find latest backup tag
    local backup_tag=$(git tag -l 'backup-*' | sort -r | head -1)

    if [[ -z "$backup_tag" ]]; then
        log_error "No backup tag found for rollback"
        return 1
    fi

    git reset --hard "$backup_tag"
    log "Rolled back to $backup_tag"

    restart_service

    return 0
}

# Main
main() {
    local check_only=false
    local force=false

    while [[ $# -gt 0 ]]; do
        case $1 in
            --check)
                check_only=true
                shift
                ;;
            --force)
                force=true
                shift
                ;;
            *)
                shift
                ;;
        esac
    done

    log "=== MIRS Auto-Update ==="

    # Acquire lock
    acquire_lock

    # Check for updates
    if ! check_updates && [[ "$force" != "true" ]]; then
        exit 0
    fi

    if [[ "$check_only" == "true" ]]; then
        log "Check only mode, not applying update"
        exit 0
    fi

    # Safety checks
    if ! in_update_window && [[ "$force" != "true" ]]; then
        log_warn "Outside update window ($UPDATE_WINDOW_START - $UPDATE_WINDOW_END)"
        log "Use --force to override"
        exit 0
    fi

    if has_active_cases; then
        log_warn "Active cases detected, skipping update for safety"
        exit 0
    fi

    # Apply update
    if ! apply_update; then
        log_error "Update failed"
        exit 1
    fi

    # Restart service
    if ! restart_service; then
        log_error "Service restart failed, rolling back..."
        rollback
        exit 1
    fi

    # Health check
    if ! health_check; then
        log_error "Health check failed, rolling back..."
        rollback
        restart_service
        exit 1
    fi

    log_success "=== Update completed successfully ==="
}

main "$@"
