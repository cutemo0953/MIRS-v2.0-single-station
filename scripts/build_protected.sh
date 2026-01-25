#!/bin/bash
# =============================================================================
# MIRS ARM64 Protected Build Script
# =============================================================================
#
# Purpose: Build MIRS backend as protected ARM64 binary using Nuitka
# Platform: Runs on x86/ARM Mac/Linux, outputs ARM64 binary
# Requirements: Docker with buildx support
#
# Usage:
#   ./scripts/build_protected.sh              # Full build
#   ./scripts/build_protected.sh --module     # Module build (faster, .so files)
#   ./scripts/build_protected.sh --prod       # Build + production image
#   ./scripts/build_protected.sh --clean      # Clean build artifacts
#
# Version: 1.0
# Date: 2026-01-25
# Reference: DEV_SPEC_COMMERCIAL_APPLIANCE_v1.5 (P1-03)
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="$PROJECT_DIR/build"
DIST_DIR="$PROJECT_DIR/dist"

BUILDER_NAME="mirs-arm64-builder"
BUILDER_IMAGE="mirs-builder:arm64"
PROD_IMAGE="mirs-hub:prod"

# =============================================================================
# Helper Functions
# =============================================================================

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_docker() {
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed. Please install Docker first."
        exit 1
    fi

    if ! docker info &> /dev/null; then
        log_error "Docker daemon is not running. Please start Docker."
        exit 1
    fi

    # Check for buildx
    if ! docker buildx version &> /dev/null; then
        log_error "Docker buildx is not available. Please update Docker."
        exit 1
    fi

    log_success "Docker and buildx are available"
}

setup_buildx() {
    log_info "Setting up Docker buildx for ARM64 cross-compilation..."

    # Check if QEMU is set up for ARM64
    if ! docker run --rm --privileged multiarch/qemu-user-static --reset -p yes &> /dev/null; then
        log_warn "QEMU setup may have issues, but continuing..."
    fi

    # Create or use existing builder
    if docker buildx inspect "$BUILDER_NAME" &> /dev/null; then
        log_info "Using existing builder: $BUILDER_NAME"
        docker buildx use "$BUILDER_NAME"
    else
        log_info "Creating new builder: $BUILDER_NAME"
        docker buildx create --name "$BUILDER_NAME" --use --platform linux/arm64,linux/amd64
    fi

    # Bootstrap the builder
    docker buildx inspect --bootstrap

    log_success "Buildx ready for ARM64"
}

clean_build() {
    log_info "Cleaning build artifacts..."
    rm -rf "$DIST_DIR"
    rm -rf "$PROJECT_DIR/__pycache__"
    find "$PROJECT_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find "$PROJECT_DIR" -type f -name "*.pyc" -delete 2>/dev/null || true
    log_success "Clean complete"
}

# =============================================================================
# Build Functions
# =============================================================================

build_standalone() {
    log_info "=== Building ARM64 Standalone Binary ==="

    # Create dist directory
    mkdir -p "$DIST_DIR"

    # Build the Docker image with Nuitka
    log_info "Building Docker image with Nuitka environment..."
    cd "$PROJECT_DIR"

    docker buildx build \
        --platform linux/arm64 \
        -f build/Dockerfile.build-arm64 \
        -t "$BUILDER_IMAGE" \
        --load \
        .

    log_success "Builder image created"

    # Run Nuitka compilation inside container
    log_info "Running Nuitka compilation (this may take 10-30 minutes)..."

    docker run --rm \
        --platform linux/arm64 \
        -v "$DIST_DIR:/output" \
        "$BUILDER_IMAGE"

    log_success "Compilation complete"

    # Verify output
    if [ -f "$DIST_DIR/mirs-hub" ]; then
        log_info "Verifying ARM64 binary..."
        file "$DIST_DIR/mirs-hub"

        # Get file size
        SIZE=$(du -h "$DIST_DIR/mirs-hub" | cut -f1)
        log_success "Binary created: dist/mirs-hub ($SIZE)"
    else
        log_error "Binary not found in dist/"
        exit 1
    fi
}

build_module() {
    log_info "=== Building ARM64 Module (.so files) ==="

    mkdir -p "$DIST_DIR"
    cd "$PROJECT_DIR"

    # Build with module mode (faster, produces .so files)
    docker buildx build \
        --platform linux/arm64 \
        -f build/Dockerfile.build-arm64 \
        -t "$BUILDER_IMAGE" \
        --load \
        .

    # Override CMD for module build
    docker run --rm \
        --platform linux/arm64 \
        -v "$DIST_DIR:/output" \
        "$BUILDER_IMAGE" \
        python -m nuitka \
            --module \
            --include-package=routes \
            --include-package=services \
            --include-package=database \
            --output-dir=/output \
            main.py

    log_success "Module build complete"
    ls -la "$DIST_DIR"/*.so 2>/dev/null || log_warn "No .so files found"
}

build_production_image() {
    log_info "=== Building Production Docker Image ==="

    if [ ! -f "$DIST_DIR/mirs-hub" ]; then
        log_error "Binary not found. Run build first: ./scripts/build_protected.sh"
        exit 1
    fi

    cd "$PROJECT_DIR"

    docker buildx build \
        --platform linux/arm64 \
        -f build/Dockerfile.prod \
        -t "$PROD_IMAGE" \
        --load \
        .

    log_success "Production image created: $PROD_IMAGE"

    # Show image info
    docker images "$PROD_IMAGE"
}

export_for_rpi() {
    log_info "=== Exporting for Raspberry Pi ==="

    if [ ! -f "$DIST_DIR/mirs-hub" ]; then
        log_error "Binary not found. Run build first."
        exit 1
    fi

    EXPORT_DIR="$DIST_DIR/mirs-rpi-$(date +%Y%m%d)"
    mkdir -p "$EXPORT_DIR"

    # Copy binary
    cp "$DIST_DIR/mirs-hub" "$EXPORT_DIR/"

    # Copy required directories
    cp -r "$PROJECT_DIR/templates" "$EXPORT_DIR/"
    cp -r "$PROJECT_DIR/static" "$EXPORT_DIR/"
    cp -r "$PROJECT_DIR/frontend" "$EXPORT_DIR/"
    cp -r "$PROJECT_DIR/fonts" "$EXPORT_DIR/"

    # Create startup script
    cat > "$EXPORT_DIR/start.sh" << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
export MIRS_DB_PATH=./data/medical_inventory.db
export MIRS_EVENTS_DB=./data/mirs.db
mkdir -p data exports backups
./mirs-hub
EOF
    chmod +x "$EXPORT_DIR/start.sh"

    # Create tarball
    TARBALL="$DIST_DIR/mirs-rpi-$(date +%Y%m%d).tar.gz"
    cd "$DIST_DIR"
    tar -czf "$TARBALL" "$(basename "$EXPORT_DIR")"

    log_success "Export complete: $TARBALL"
    log_info "Transfer to RPi: scp $TARBALL pi@<rpi-ip>:~/"
}

# =============================================================================
# Main
# =============================================================================

show_help() {
    echo "MIRS ARM64 Protected Build Script"
    echo ""
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  (no args)    Full standalone build (produces single binary)"
    echo "  --module     Module build (faster, produces .so files)"
    echo "  --prod       Build standalone + production Docker image"
    echo "  --export     Build + export tarball for RPi deployment"
    echo "  --clean      Clean build artifacts"
    echo "  --help       Show this help"
    echo ""
    echo "Examples:"
    echo "  $0                    # Build ARM64 binary"
    echo "  $0 --prod             # Build binary + Docker image"
    echo "  $0 --export           # Build + create RPi deployment package"
}

main() {
    echo ""
    echo "========================================"
    echo "  MIRS ARM64 Protected Build"
    echo "  $(date)"
    echo "========================================"
    echo ""

    # Check requirements
    check_docker

    case "${1:-}" in
        --clean)
            clean_build
            ;;
        --module)
            setup_buildx
            build_module
            ;;
        --prod)
            setup_buildx
            build_standalone
            build_production_image
            ;;
        --export)
            setup_buildx
            build_standalone
            export_for_rpi
            ;;
        --help|-h)
            show_help
            ;;
        "")
            setup_buildx
            build_standalone
            ;;
        *)
            log_error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac

    echo ""
    log_success "=== Build process complete ==="
    echo ""
}

main "$@"
