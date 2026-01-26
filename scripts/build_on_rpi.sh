#!/bin/bash
# =============================================================================
# MIRS Native Build Script (for Raspberry Pi)
# =============================================================================
#
# Purpose: Build MIRS directly on Raspberry Pi (native ARM64 compilation)
# Platform: Raspberry Pi 5 (ARM64)
# Requirements: Python 3.11, gcc, build-essential
#
# Usage:
#   ./scripts/build_on_rpi.sh           # Full standalone build
#   ./scripts/build_on_rpi.sh --module  # Module build (faster)
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DIST_DIR="$PROJECT_DIR/dist"

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# =============================================================================
# Check Requirements
# =============================================================================

check_system() {
    log_info "Checking system requirements..."

    # Check if ARM64
    ARCH=$(uname -m)
    if [[ "$ARCH" != "aarch64" && "$ARCH" != "arm64" ]]; then
        log_error "This script is for ARM64 (Raspberry Pi). Detected: $ARCH"
        log_info "For cross-compilation, use: ./scripts/build_protected.sh"
        exit 1
    fi

    # Check Python version (3.11, 3.12, or 3.13)
    PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1,2)
    if [[ "$PYTHON_VERSION" != "3.11" && "$PYTHON_VERSION" != "3.12" && "$PYTHON_VERSION" != "3.13" ]]; then
        log_error "Python 3.11, 3.12, or 3.13 required. Found: $PYTHON_VERSION"
        exit 1
    fi

    # Check gcc
    if ! command -v gcc &> /dev/null; then
        log_error "gcc not found. Install: sudo apt install build-essential"
        exit 1
    fi

    log_success "System check passed (ARM64, Python $PYTHON_VERSION)"
}

install_nuitka() {
    log_info "Installing Nuitka..."

    pip3 install --user nuitka ordered-set zstandard

    # Verify installation
    if python3 -m nuitka --version &> /dev/null; then
        log_success "Nuitka installed: $(python3 -m nuitka --version)"
    else
        log_error "Nuitka installation failed"
        exit 1
    fi
}

# =============================================================================
# Build Functions
# =============================================================================

build_standalone() {
    log_info "=== Building Standalone Binary ==="
    log_info "This will take 15-30 minutes on RPi 5..."
    log_info "(--standalone is MANDATORY per OTA v1.2 spec - includes all dependencies)"

    mkdir -p "$DIST_DIR"
    cd "$PROJECT_DIR"

    # CRITICAL: --standalone is MANDATORY per DEV_SPEC_OTA_ARCHITECTURE_v1.2
    # This ensures the binary includes ALL dependencies and doesn't rely on
    # the system Python environment (which may have different package versions).
    python3 -m nuitka \
        --standalone \
        --onefile \
        --assume-yes-for-downloads \
        --include-package=routes \
        --include-package=services \
        --include-package=database \
        --include-package=models \
        --include-package=config \
        --include-data-dir=templates=templates \
        --include-data-dir=static=static \
        --include-data-dir=frontend=frontend \
        --include-data-dir=fonts=fonts \
        --include-data-dir=database/migrations=database/migrations \
        --include-data-dir=database/profiles=database/profiles \
        --include-data-files=database/*.sql=database/ \
        --output-dir="$DIST_DIR" \
        --output-filename=mirs-server \
        --company-name=xIRS \
        --product-name=MIRS-Server \
        --product-version=1.5.0 \
        --lto=yes \
        --jobs=2 \
        main.py

    if [ -f "$DIST_DIR/mirs-server" ]; then
        chmod +x "$DIST_DIR/mirs-server"
        SIZE=$(du -h "$DIST_DIR/mirs-server" | cut -f1)
        log_success "Build complete: dist/mirs-server ($SIZE)"
    else
        log_error "Build failed - binary not found"
        exit 1
    fi
}

build_module() {
    log_info "=== Building Python Module ==="

    mkdir -p "$DIST_DIR"
    cd "$PROJECT_DIR"

    python3 -m nuitka \
        --module \
        --include-package=routes \
        --include-package=services \
        --include-package=database \
        --output-dir="$DIST_DIR" \
        --jobs=4 \
        main.py

    log_success "Module build complete"
    ls -la "$DIST_DIR"/*.so 2>/dev/null || true
}

# =============================================================================
# Main
# =============================================================================

main() {
    echo ""
    echo "========================================"
    echo "  MIRS Native ARM64 Build (RPi)"
    echo "  $(date)"
    echo "========================================"
    echo ""

    check_system

    # Check if Nuitka is installed
    if ! python3 -m nuitka --version &> /dev/null; then
        install_nuitka
    fi

    case "${1:-}" in
        --module)
            build_module
            ;;
        --help|-h)
            echo "Usage: $0 [--module|--help]"
            echo "  (no args)  Build standalone binary"
            echo "  --module   Build Python module (.so)"
            ;;
        *)
            build_standalone
            ;;
    esac

    echo ""
    log_success "=== Build complete ==="
    echo ""
}

main "$@"
