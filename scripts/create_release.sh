#!/bin/bash
# =============================================================================
# xIRS Release Packaging Script (v2.0)
# =============================================================================
#
# Purpose: Package xIRS (MIRS/CIRS) for GitHub Release with v1.2 spec compliance
#
# Features:
#   - release.json v2 manifest generation
#   - Minisign signature for binary AND manifest
#   - Support for both MIRS and CIRS assets
#   - Uploads to dedicated xirs-releases repo
#
# Usage:
#   ./scripts/create_release.sh [version] [command]
#   ./scripts/create_release.sh 2.4.0 package   # Package only
#   ./scripts/create_release.sh 2.4.0 sign      # Sign with minisign
#   ./scripts/create_release.sh 2.4.0 upload    # Upload to GitHub
#   ./scripts/create_release.sh 2.4.0 all       # Package + Sign + Upload
#
# Output:
#   releases/
#     release.json                    # v2 manifest
#     release.json.minisig            # Manifest signature
#     mirs-server-2.4.0-arm64         # MIRS binary
#     mirs-server-2.4.0-arm64.minisig # Binary signature
#     cirs-server-2.4.0-arm64         # CIRS binary (if available)
#     cirs-server-2.4.0-arm64.minisig # Binary signature
#
# Version: 2.0
# Date: 2026-01-26
# Reference: DEV_SPEC_OTA_ARCHITECTURE_v1.2
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
RELEASES_DIR="$PROJECT_DIR/releases"

# v1.2: GitHub Release configuration
GITHUB_ORG="cutemo0953"
GITHUB_RELEASES_REPO="xirs-releases"
GITHUB_FULL_REPO="${GITHUB_ORG}/${GITHUB_RELEASES_REPO}"

# Minisign key paths (these should be set up securely)
MINISIGN_SECRET_KEY="${MINISIGN_SECRET_KEY:-$HOME/.minisign/minisign.key}"

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

# =============================================================================
# Get Version
# =============================================================================

get_version() {
    if [ -n "$1" ]; then
        echo "$1"
    else
        # Extract from config
        grep -o 'CURRENT_VERSION = "[^"]*"' "$PROJECT_DIR/services/ota_service.py" 2>/dev/null | cut -d'"' -f2 || echo "2.4.0"
    fi
}

# =============================================================================
# Package Binaries
# =============================================================================

package_binary() {
    local VERSION=$1
    local MIRS_BINARY="mirs-server-${VERSION}-arm64"
    local CIRS_BINARY="cirs-server-${VERSION}-arm64"

    log_info "Packaging xIRS v${VERSION}..."

    mkdir -p "$RELEASES_DIR"

    # Package MIRS
    if [ -f "$PROJECT_DIR/dist/mirs-server" ]; then
        cp "$PROJECT_DIR/dist/mirs-server" "$RELEASES_DIR/$MIRS_BINARY"
        log_success "MIRS binary copied: $MIRS_BINARY"

        # Generate SHA256
        cd "$RELEASES_DIR"
        sha256sum "$MIRS_BINARY" > "${MIRS_BINARY}.sha256"
        MIRS_SHA256=$(cat "${MIRS_BINARY}.sha256" | awk '{print $1}')
        MIRS_SIZE=$(stat -f%z "$MIRS_BINARY" 2>/dev/null || stat -c%s "$MIRS_BINARY" 2>/dev/null)
        log_success "MIRS checksum: $MIRS_SHA256"
    else
        log_warn "MIRS binary not found at dist/mirs-server"
        log_info "Run: ./scripts/build_on_rpi.sh first"
    fi

    # Package CIRS (optional)
    CIRS_DIR="$PROJECT_DIR/../CIRS"
    if [ -f "$CIRS_DIR/dist/cirs-server" ]; then
        cp "$CIRS_DIR/dist/cirs-server" "$RELEASES_DIR/$CIRS_BINARY"
        log_success "CIRS binary copied: $CIRS_BINARY"

        cd "$RELEASES_DIR"
        sha256sum "$CIRS_BINARY" > "${CIRS_BINARY}.sha256"
        CIRS_SHA256=$(cat "${CIRS_BINARY}.sha256" | awk '{print $1}')
        CIRS_SIZE=$(stat -f%z "$CIRS_BINARY" 2>/dev/null || stat -c%s "$CIRS_BINARY" 2>/dev/null)
        log_success "CIRS checksum: $CIRS_SHA256"
    else
        log_warn "CIRS binary not found at ../CIRS/dist/cirs-server (optional)"
        CIRS_SHA256=""
        CIRS_SIZE=""
    fi
}

# =============================================================================
# Generate release.json v2 Manifest
# =============================================================================

generate_manifest_v2() {
    local VERSION=$1
    local MANIFEST_FILE="$RELEASES_DIR/release.json"

    log_info "Generating release.json v2 manifest..."

    local RELEASE_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    local BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    local COMMIT_HASH=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

    # Calculate checksums if binaries exist
    local MIRS_BINARY="mirs-server-${VERSION}-arm64"
    local CIRS_BINARY="cirs-server-${VERSION}-arm64"

    local MIRS_SHA256=""
    local MIRS_SIZE=""
    local CIRS_SHA256=""
    local CIRS_SIZE=""

    if [ -f "$RELEASES_DIR/$MIRS_BINARY" ]; then
        MIRS_SHA256=$(sha256sum "$RELEASES_DIR/$MIRS_BINARY" | awk '{print $1}')
        MIRS_SIZE=$(stat -f%z "$RELEASES_DIR/$MIRS_BINARY" 2>/dev/null || stat -c%s "$RELEASES_DIR/$MIRS_BINARY" 2>/dev/null)
    fi

    if [ -f "$RELEASES_DIR/$CIRS_BINARY" ]; then
        CIRS_SHA256=$(sha256sum "$RELEASES_DIR/$CIRS_BINARY" | awk '{print $1}')
        CIRS_SIZE=$(stat -f%z "$RELEASES_DIR/$CIRS_BINARY" 2>/dev/null || stat -c%s "$RELEASES_DIR/$CIRS_BINARY" 2>/dev/null)
    fi

    # Build CIRS asset block (only if binary exists)
    local CIRS_ASSET=""
    if [ -n "$CIRS_SHA256" ]; then
        CIRS_ASSET=$(cat << CIRSEOF
,
    "cirs": {
      "name": "cirs-server-${VERSION}-arm64",
      "download_url": "https://github.com/${GITHUB_FULL_REPO}/releases/download/v${VERSION}/cirs-server-${VERSION}-arm64",
      "sha256": "${CIRS_SHA256}",
      "signature_url": "https://github.com/${GITHUB_FULL_REPO}/releases/download/v${VERSION}/cirs-server-${VERSION}-arm64.minisig",
      "size_bytes": ${CIRS_SIZE:-0},
      "min_upgrade_version": "1.0.0",
      "requires_migration": false
    }
CIRSEOF
)
    fi

    cat > "$MANIFEST_FILE" << EOF
{
  "schema_version": "2.0",
  "version": "${VERSION}",
  "channel": "stable",
  "release_date": "${RELEASE_DATE}",
  "commit_hash": "${COMMIT_HASH}",
  "build_date": "${BUILD_DATE}",

  "signature": {
    "algorithm": "minisign",
    "key_id": "RWQv22qwGAFuMINaVoJEAxa0DV7ox9KMTVqwpP3DMvhhLY0nFIe5KdHC",
    "manifest_signature": "release.json.minisig"
  },

  "assets": {
    "mirs": {
      "name": "mirs-server-${VERSION}-arm64",
      "download_url": "https://github.com/${GITHUB_FULL_REPO}/releases/download/v${VERSION}/mirs-server-${VERSION}-arm64",
      "sha256": "${MIRS_SHA256}",
      "signature_url": "https://github.com/${GITHUB_FULL_REPO}/releases/download/v${VERSION}/mirs-server-${VERSION}-arm64.minisig",
      "size_bytes": ${MIRS_SIZE:-0},
      "min_upgrade_version": "2.0.0",
      "requires_migration": false
    }${CIRS_ASSET}
  },

  "migration": {
    "requires_migration": false,
    "migration_type": "none",
    "backward_compatible": true,
    "min_rollback_version": null,
    "migration_script": null
  },

  "breaking_changes": {
    "has_breaking": false,
    "reasons": [],
    "requires_manual_approval": false
  },

  "constraints": {
    "min_current_version": "2.0.0",
    "max_current_version": null,
    "allowed_channels": ["stable", "beta"],
    "force_update": false
  },

  "smoke_test": {
    "endpoints": [
      {"path": "/api/health", "expected_status": 200},
      {"path": "/api/ota/status", "expected_status": 200},
      {"path": "/api/equipment", "expected_status": 200}
    ],
    "timeout_seconds": 60,
    "retry_count": 3
  },

  "release_notes": "xIRS v${VERSION} release. See GitHub release for full changelog."
}
EOF

    log_success "Manifest generated: $MANIFEST_FILE"
    cat "$MANIFEST_FILE"
}

# =============================================================================
# Sign with Minisign
# =============================================================================

sign_files() {
    local VERSION=$1

    if ! command -v minisign &> /dev/null; then
        log_error "minisign not installed. Install: apt install minisign"
        log_info "Generate keys with: minisign -G -p pubkey.pub -s minisign.key"
        return 1
    fi

    if [ ! -f "$MINISIGN_SECRET_KEY" ]; then
        log_error "Minisign secret key not found at: $MINISIGN_SECRET_KEY"
        log_info "Set MINISIGN_SECRET_KEY environment variable or place key at default location"
        return 1
    fi

    log_info "Signing files with minisign..."

    cd "$RELEASES_DIR"

    # Sign manifest (CRITICAL per v1.2 spec - Gemini G3)
    if [ -f "release.json" ]; then
        minisign -S -s "$MINISIGN_SECRET_KEY" -m "release.json" -x "release.json.minisig"
        log_success "Signed: release.json -> release.json.minisig"
    fi

    # Sign MIRS binary
    local MIRS_BINARY="mirs-server-${VERSION}-arm64"
    if [ -f "$MIRS_BINARY" ]; then
        minisign -S -s "$MINISIGN_SECRET_KEY" -m "$MIRS_BINARY" -x "${MIRS_BINARY}.minisig"
        log_success "Signed: $MIRS_BINARY -> ${MIRS_BINARY}.minisig"
    fi

    # Sign CIRS binary
    local CIRS_BINARY="cirs-server-${VERSION}-arm64"
    if [ -f "$CIRS_BINARY" ]; then
        minisign -S -s "$MINISIGN_SECRET_KEY" -m "$CIRS_BINARY" -x "${CIRS_BINARY}.minisig"
        log_success "Signed: $CIRS_BINARY -> ${CIRS_BINARY}.minisig"
    fi

    log_success "All files signed"
}

# =============================================================================
# Generate Release Notes
# =============================================================================

generate_release_notes() {
    local VERSION=$1
    local NOTES_FILE="$RELEASES_DIR/RELEASE_NOTES.md"

    log_info "Generating release notes..."

    cat > "$NOTES_FILE" << EOF
# xIRS v${VERSION}

**Release Date:** $(date +%Y-%m-%d)
**Platform:** ARM64 (Raspberry Pi 5)
**Manifest Schema:** v2.0

## Components

| Component | Binary | Size |
|-----------|--------|------|
| MIRS | mirs-server-${VERSION}-arm64 | $(du -h "$RELEASES_DIR/mirs-server-${VERSION}-arm64" 2>/dev/null | cut -f1 || echo "N/A") |
| CIRS | cirs-server-${VERSION}-arm64 | $(du -h "$RELEASES_DIR/cirs-server-${VERSION}-arm64" 2>/dev/null | cut -f1 || echo "N/A") |

## What's New

- OTA v1.2 spec compliant release
- Minisign signature verification
- Atomic update protocol support
- Anti-downgrade protection

## Installation

### OTA Update (Recommended)

The xIRS OTA client will automatically detect this release:

\`\`\`bash
# Check for updates
curl http://localhost:8000/api/ota/check

# Apply update (if available)
curl -X POST http://localhost:8000/api/ota/apply
\`\`\`

### Manual Installation

\`\`\`bash
# Download binary
wget https://github.com/${GITHUB_FULL_REPO}/releases/download/v${VERSION}/mirs-server-${VERSION}-arm64

# Download signature
wget https://github.com/${GITHUB_FULL_REPO}/releases/download/v${VERSION}/mirs-server-${VERSION}-arm64.minisig

# Verify signature (requires public key)
minisign -Vm mirs-server-${VERSION}-arm64 -p /etc/mirs/ota_pubkey.pub

# Make executable and run
chmod +x mirs-server-${VERSION}-arm64
MIRS_PORT=8000 ./mirs-server-${VERSION}-arm64
\`\`\`

## Verification

All binaries and the manifest are signed with minisign.
Public key ID: \`306E0118B06ADB2F\`

---
*xIRS - Medical Device Inventory System*
*De Novo Orthopedics Inc. / 谷盺生物科技股份有限公司*
EOF

    log_success "Release notes: $NOTES_FILE"
}

# =============================================================================
# Upload to GitHub Releases Repo
# =============================================================================

upload_to_github() {
    local VERSION=$1

    if ! command -v gh &> /dev/null; then
        log_error "GitHub CLI (gh) not installed."
        log_info "Install: brew install gh"
        return 1
    fi

    log_info "Creating GitHub release v${VERSION} on ${GITHUB_FULL_REPO}..."

    cd "$RELEASES_DIR"

    # Build list of files to upload
    local FILES=""
    [ -f "release.json" ] && FILES="$FILES release.json"
    [ -f "release.json.minisig" ] && FILES="$FILES release.json.minisig"
    [ -f "mirs-server-${VERSION}-arm64" ] && FILES="$FILES mirs-server-${VERSION}-arm64"
    [ -f "mirs-server-${VERSION}-arm64.minisig" ] && FILES="$FILES mirs-server-${VERSION}-arm64.minisig"
    [ -f "mirs-server-${VERSION}-arm64.sha256" ] && FILES="$FILES mirs-server-${VERSION}-arm64.sha256"
    [ -f "cirs-server-${VERSION}-arm64" ] && FILES="$FILES cirs-server-${VERSION}-arm64"
    [ -f "cirs-server-${VERSION}-arm64.minisig" ] && FILES="$FILES cirs-server-${VERSION}-arm64.minisig"
    [ -f "cirs-server-${VERSION}-arm64.sha256" ] && FILES="$FILES cirs-server-${VERSION}-arm64.sha256"

    log_info "Uploading files: $FILES"

    # Create release with assets on the releases repo
    gh release create "v${VERSION}" \
        --repo "${GITHUB_FULL_REPO}" \
        --title "xIRS v${VERSION}" \
        --notes-file "RELEASE_NOTES.md" \
        $FILES

    log_success "GitHub release created: v${VERSION}"
    log_info "URL: https://github.com/${GITHUB_FULL_REPO}/releases/tag/v${VERSION}"
}

# =============================================================================
# Main
# =============================================================================

main() {
    echo ""
    echo "========================================"
    echo "  xIRS Release Packager (v2.0)"
    echo "  OTA Spec: v1.2 (Final)"
    echo "  $(date)"
    echo "========================================"
    echo ""

    VERSION=$(get_version "$1")
    log_info "Version: $VERSION"
    log_info "Target repo: $GITHUB_FULL_REPO"

    case "${2:-package}" in
        package)
            package_binary "$VERSION"
            generate_manifest_v2 "$VERSION"
            generate_release_notes "$VERSION"
            echo ""
            log_success "=== Package complete ==="
            echo ""
            echo "Files in $RELEASES_DIR:"
            ls -la "$RELEASES_DIR"
            echo ""
            log_info "Next: $0 $VERSION sign"
            ;;
        sign)
            sign_files "$VERSION"
            echo ""
            log_success "=== Signing complete ==="
            echo ""
            log_info "Next: $0 $VERSION upload"
            ;;
        upload)
            upload_to_github "$VERSION"
            ;;
        all)
            package_binary "$VERSION"
            generate_manifest_v2 "$VERSION"
            generate_release_notes "$VERSION"
            sign_files "$VERSION"
            upload_to_github "$VERSION"
            ;;
        manifest)
            # Just generate manifest (useful for testing)
            generate_manifest_v2 "$VERSION"
            ;;
        *)
            echo "Usage: $0 [version] [command]"
            echo ""
            echo "Commands:"
            echo "  package   - Package binaries and generate manifest"
            echo "  sign      - Sign files with minisign"
            echo "  upload    - Upload to GitHub releases"
            echo "  all       - Do everything (package + sign + upload)"
            echo "  manifest  - Only generate release.json manifest"
            echo ""
            echo "Examples:"
            echo "  $0 2.4.0 package   # Package only"
            echo "  $0 2.4.0 sign      # Sign with minisign"
            echo "  $0 2.4.0 upload    # Upload to GitHub"
            echo "  $0 2.4.0 all       # Complete release"
            echo ""
            echo "Environment:"
            echo "  MINISIGN_SECRET_KEY  Path to minisign secret key"
            echo "                       Default: \$HOME/.minisign/minisign.key"
            ;;
    esac
}

main "$@"
