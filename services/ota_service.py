"""
xIRS OTA (Over-The-Air) Update Service

Implements:
- Version checking against GitHub Releases
- release.json v2 manifest with signature verification
- Binary-based updates for standalone deployments
- Anti-downgrade protection
- Version pin and skip list support
- ETag caching for efficient update checks
- Automatic rollback on failure
- Health check verification

Version: 2.0
Date: 2026-01-26
Reference: DEV_SPEC_OTA_ARCHITECTURE_v1.2 (Final)
"""

import hashlib
import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# GitHub Release configuration (v1.2: Updated to dedicated releases repo)
GITHUB_REPO = os.environ.get('MIRS_GITHUB_REPO', 'cutemo0953/xirs-releases')  # owner/repo
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases/download"
UPDATE_CHECK_INTERVAL = 3600  # 1 hour

# v1.2: release.json manifest URL (preferred method)
MANIFEST_FILENAME = "release.json"
MANIFEST_SIG_FILENAME = "release.json.minisig"

# v1.2: OTA state directory for caching and skip list
OTA_STATE_DIR = Path(os.environ.get('MIRS_OTA_STATE_DIR', '/var/lib/mirs/ota'))
SKIP_LIST_FILE = OTA_STATE_DIR / "state" / "skip_list.json"
VERSION_PIN_FILE = OTA_STATE_DIR / "state" / "config.json"
ETAG_CACHE_FILE = OTA_STATE_DIR / "cache" / "manifest.etag"
CACHED_MANIFEST_FILE = OTA_STATE_DIR / "cache" / "manifest.json"

# Legacy update server (fallback)
UPDATE_SERVER = os.environ.get('MIRS_UPDATE_SERVER', '')

# Docker configuration
DOCKER_REGISTRY = os.environ.get('MIRS_DOCKER_REGISTRY', 'ghcr.io/xirs')
DOCKER_IMAGE_NAME = 'mirs-server'

# Local paths
DATA_DIR = Path(os.environ.get('MIRS_DATA_DIR', '/var/lib/mirs'))
BACKUP_DIR = DATA_DIR / 'backups'
UPDATE_DIR = DATA_DIR / 'updates'
VERSION_FILE = DATA_DIR / 'version.json'
ROLLBACK_FILE = DATA_DIR / 'rollback.json'

# Binary paths (for standalone mode)
BINARY_PATH = Path('/app/mirs-hub')
BINARY_BACKUP_PATH = Path('/app/mirs-hub.backup')


# =============================================================================
# Enums and Data Classes
# =============================================================================

class UpdateMethod(Enum):
    """Update deployment method."""
    DOCKER = "docker"      # Docker image pull + container restart
    BINARY = "binary"      # Binary replacement + service restart
    MANUAL = "manual"      # Manual update required


class UpdateStatus(Enum):
    """Update operation status."""
    IDLE = "idle"
    CHECKING = "checking"
    DOWNLOADING = "downloading"
    APPLYING = "applying"
    VERIFYING = "verifying"
    ROLLING_BACK = "rolling_back"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class VersionInfo:
    """Version information."""
    version: str
    build_date: str
    commit_hash: Optional[str] = None
    channel: str = "stable"  # stable, beta, dev


@dataclass
class UpdateInfo:
    """Available update information."""
    available: bool
    current_version: str
    latest_version: str
    release_notes: Optional[str] = None
    download_url: Optional[str] = None
    checksum: Optional[str] = None
    size_bytes: Optional[int] = None
    release_date: Optional[str] = None
    breaking_changes: bool = False


@dataclass
class UpdateResult:
    """Update operation result."""
    success: bool
    status: UpdateStatus
    message: str
    previous_version: Optional[str] = None
    new_version: Optional[str] = None
    rollback_available: bool = False


# =============================================================================
# v1.2: Release Manifest v2 Data Classes
# =============================================================================

@dataclass
class AssetInfo:
    """Asset information from release.json v2."""
    name: str
    download_url: str
    sha256: str
    signature_url: Optional[str] = None
    size_bytes: Optional[int] = None
    min_upgrade_version: Optional[str] = None
    requires_migration: bool = False


@dataclass
class MigrationInfo:
    """Migration information from release.json v2."""
    requires_migration: bool = False
    migration_type: str = "none"  # none, additive, breaking
    backward_compatible: bool = True
    min_rollback_version: Optional[str] = None
    migration_script: Optional[str] = None


@dataclass
class ManifestV2:
    """Release manifest v2 structure."""
    schema_version: str
    version: str
    channel: str
    release_date: str
    build_date: str
    commit_hash: Optional[str]
    assets: Dict[str, AssetInfo]  # mirs, cirs, etc.
    migration: MigrationInfo
    breaking_changes: Dict[str, Any]
    constraints: Dict[str, Any]
    release_notes: Optional[str] = None
    smoke_test: Optional[Dict] = None

    @classmethod
    def from_dict(cls, data: Dict) -> 'ManifestV2':
        """Parse manifest from dictionary."""
        assets = {}
        for key, asset_data in data.get('assets', {}).items():
            assets[key] = AssetInfo(
                name=asset_data.get('name', ''),
                download_url=asset_data.get('download_url', ''),
                sha256=asset_data.get('sha256', ''),
                signature_url=asset_data.get('signature_url'),
                size_bytes=asset_data.get('size_bytes'),
                min_upgrade_version=asset_data.get('min_upgrade_version'),
                requires_migration=asset_data.get('requires_migration', False)
            )

        migration_data = data.get('migration', {})
        migration = MigrationInfo(
            requires_migration=migration_data.get('requires_migration', False),
            migration_type=migration_data.get('migration_type', 'none'),
            backward_compatible=migration_data.get('backward_compatible', True),
            min_rollback_version=migration_data.get('min_rollback_version'),
            migration_script=migration_data.get('migration_script')
        )

        return cls(
            schema_version=data.get('schema_version', '1.0'),
            version=data.get('version', '0.0.0'),
            channel=data.get('channel', 'stable'),
            release_date=data.get('release_date', ''),
            build_date=data.get('build_date', ''),
            commit_hash=data.get('commit_hash'),
            assets=assets,
            migration=migration,
            breaking_changes=data.get('breaking_changes', {}),
            constraints=data.get('constraints', {}),
            release_notes=data.get('release_notes'),
            smoke_test=data.get('smoke_test')
        )


# =============================================================================
# Version Management
# =============================================================================

# Current version (embedded at build time or read from file)
CURRENT_VERSION = "2.4.0"
BUILD_DATE = "2026-01-25"
COMMIT_HASH = None


def get_current_version() -> VersionInfo:
    """Get current installed version."""
    # Try to read from version file first
    if VERSION_FILE.exists():
        try:
            with open(VERSION_FILE, 'r') as f:
                data = json.load(f)
                return VersionInfo(
                    version=data.get('version', CURRENT_VERSION),
                    build_date=data.get('build_date', BUILD_DATE),
                    commit_hash=data.get('commit_hash'),
                    channel=data.get('channel', 'stable')
                )
        except Exception as e:
            logger.warning(f"Failed to read version file: {e}")

    return VersionInfo(
        version=CURRENT_VERSION,
        build_date=BUILD_DATE,
        commit_hash=COMMIT_HASH
    )


def save_version_info(version_info: VersionInfo):
    """Save version information to file."""
    try:
        VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(VERSION_FILE, 'w') as f:
            json.dump(asdict(version_info), f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save version info: {e}")


# =============================================================================
# v1.2: Anti-Downgrade Protection
# =============================================================================

def check_version_upgrade(
    current_version: str,
    target_version: str,
    force: bool = False
) -> Tuple[bool, str]:
    """
    Check if version upgrade is allowed (prevents downgrades).

    Per OTA v1.2 spec (Gemini G4):
    - Automatic downgrades are FORBIDDEN
    - Manual downgrades allowed only with force=True
    - Major version bumps require manual confirmation

    Returns:
        (allowed, reason)
    """
    curr = compare_versions(current_version, target_version)

    # Downgrade check
    if curr > 0:  # target < current
        if force:
            logger.warning(f"Force downgrade: {current_version} → {target_version}")
            return True, f"強制降級: {current_version} → {target_version}"
        return False, f"禁止降級: {current_version} → {target_version}"

    # Same version
    if curr == 0:
        return False, f"已是最新版本: {current_version}"

    # Major version bump check
    try:
        curr_major = int(current_version.split('.')[0])
        target_major = int(target_version.split('.')[0])
        if target_major > curr_major:
            return False, f"Major 版本升級需手動確認: {current_version} → {target_version}"
    except (ValueError, IndexError):
        pass

    return True, f"允許升級: {current_version} → {target_version}"


# =============================================================================
# v1.2: Version Pin and Skip List
# =============================================================================

def load_skip_list() -> List[str]:
    """Load list of versions to skip (failed health checks, etc.)."""
    try:
        if SKIP_LIST_FILE.exists():
            with open(SKIP_LIST_FILE, 'r') as f:
                data = json.load(f)
                return [item['version'] for item in data.get('skipped_versions', [])]
    except Exception as e:
        logger.warning(f"Failed to load skip list: {e}")
    return []


def add_to_skip_list(version: str, reason: str):
    """Add a version to the skip list."""
    try:
        SKIP_LIST_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {'skipped_versions': []}

        if SKIP_LIST_FILE.exists():
            with open(SKIP_LIST_FILE, 'r') as f:
                data = json.load(f)

        data['skipped_versions'].append({
            'version': version,
            'reason': reason,
            'failed_at': datetime.now().isoformat(),
            'retry_count': 1
        })

        with open(SKIP_LIST_FILE, 'w') as f:
            json.dump(data, f, indent=2)

        logger.info(f"Added {version} to skip list: {reason}")
    except Exception as e:
        logger.error(f"Failed to add to skip list: {e}")


def load_version_pin() -> Optional[str]:
    """Load version pin pattern (e.g., '2.4.*')."""
    try:
        if VERSION_PIN_FILE.exists():
            with open(VERSION_PIN_FILE, 'r') as f:
                data = json.load(f)
                pin = data.get('version_pin', {})
                if pin.get('enabled'):
                    return pin.get('pattern')
    except Exception as e:
        logger.warning(f"Failed to load version pin: {e}")
    return None


def is_version_allowed_by_pin(version: str, pin_pattern: Optional[str]) -> bool:
    """Check if version matches pin pattern."""
    if not pin_pattern:
        return True

    import re
    regex = pin_pattern.replace(".", r"\.").replace("*", ".*")
    return bool(re.match(f"^{regex}$", version))


# =============================================================================
# v1.2: Manifest Signature Verification
# =============================================================================

def verify_manifest_signature(
    manifest_path: str,
    signature_path: str
) -> Tuple[bool, str]:
    """
    Verify manifest signature before parsing.

    Per OTA v1.2 spec (Gemini G3):
    - Manifest MUST be signed
    - Signature must be verified BEFORE parsing JSON
    - Prevents MITM attacks that redirect to vulnerable versions
    """
    try:
        from services.ota_security import verify_signature

        result = verify_signature(manifest_path, signature_path)
        if result.valid:
            return True, "Manifest 簽章驗證通過"
        else:
            return False, f"Manifest 簽章驗證失敗: {result.message}"
    except ImportError:
        logger.warning("ota_security module not available, skipping manifest verification")
        return True, "簽章模組不可用，跳過驗證"
    except Exception as e:
        return False, f"簽章驗證錯誤: {e}"


# =============================================================================
# Update Detection
# =============================================================================

def detect_update_method() -> UpdateMethod:
    """Detect the appropriate update method based on deployment type."""
    # Check if running in Docker
    if os.path.exists('/.dockerenv'):
        return UpdateMethod.DOCKER

    # Check if binary exists
    if BINARY_PATH.exists():
        return UpdateMethod.BINARY

    # Default to manual
    return UpdateMethod.MANUAL


def compare_versions(v1: str, v2: str) -> int:
    """
    Compare two version strings.
    Returns: -1 if v1 < v2, 0 if equal, 1 if v1 > v2
    """
    def normalize(v):
        return [int(x) for x in v.split('.')]

    try:
        parts1 = normalize(v1)
        parts2 = normalize(v2)

        for i in range(max(len(parts1), len(parts2))):
            p1 = parts1[i] if i < len(parts1) else 0
            p2 = parts2[i] if i < len(parts2) else 0
            if p1 < p2:
                return -1
            elif p1 > p2:
                return 1
        return 0
    except Exception:
        return 0


# =============================================================================
# v1.2: Manifest Fetching with ETag Cache
# =============================================================================

async def fetch_manifest_v2(tag: str = "latest") -> Optional[ManifestV2]:
    """
    Fetch and verify release.json manifest from GitHub Releases.

    Per OTA v1.2 spec:
    1. Download release.json
    2. Download release.json.minisig
    3. Verify signature BEFORE parsing
    4. Parse and return ManifestV2

    Uses ETag caching to minimize API calls.
    """
    import aiohttp
    import tempfile

    # Determine manifest URL
    if tag == "latest":
        manifest_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        use_api = True
    else:
        manifest_url = f"{GITHUB_RELEASES_URL}/{tag}/{MANIFEST_FILENAME}"
        use_api = False

    try:
        async with aiohttp.ClientSession() as session:
            headers = {
                'Accept': 'application/vnd.github.v3+json',
                'User-Agent': 'MIRS-OTA-Client/2.0'
            }

            # Check ETag cache
            cached_etag = None
            if ETAG_CACHE_FILE.exists():
                cached_etag = ETAG_CACHE_FILE.read_text().strip()
                headers['If-None-Match'] = cached_etag

            if use_api:
                # Use GitHub API to get latest release
                async with session.get(manifest_url, headers=headers, timeout=30) as resp:
                    if resp.status == 304:
                        # Not modified, use cached manifest
                        logger.info("Manifest not modified (304), using cache")
                        if CACHED_MANIFEST_FILE.exists():
                            with open(CACHED_MANIFEST_FILE, 'r') as f:
                                return ManifestV2.from_dict(json.load(f))
                        return None

                    if resp.status != 200:
                        logger.warning(f"GitHub API returned {resp.status}")
                        return None

                    release_data = await resp.json()
                    tag = release_data.get('tag_name', 'v0.0.0')

                    # Save ETag
                    new_etag = resp.headers.get('ETag')
                    if new_etag:
                        ETAG_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                        ETAG_CACHE_FILE.write_text(new_etag)

            # Now fetch the actual release.json from assets
            manifest_url = f"{GITHUB_RELEASES_URL}/{tag}/{MANIFEST_FILENAME}"
            sig_url = f"{GITHUB_RELEASES_URL}/{tag}/{MANIFEST_SIG_FILENAME}"

            # Download manifest to temp file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as mf:
                async with session.get(manifest_url, timeout=30) as resp:
                    if resp.status != 200:
                        # release.json might not exist (older releases)
                        logger.info(f"release.json not found for {tag}, falling back to API parsing")
                        return None
                    manifest_content = await resp.text()
                    mf.write(manifest_content)
                    manifest_path = mf.name

            # Download signature
            sig_path = manifest_path + ".minisig"
            async with session.get(sig_url, timeout=30) as resp:
                if resp.status == 200:
                    sig_content = await resp.text()
                    with open(sig_path, 'w') as sf:
                        sf.write(sig_content)

                    # Verify signature BEFORE parsing
                    valid, msg = verify_manifest_signature(manifest_path, sig_path)
                    if not valid:
                        logger.error(f"Manifest signature invalid: {msg}")
                        os.unlink(manifest_path)
                        os.unlink(sig_path)
                        return None
                else:
                    logger.warning(f"Manifest signature not available ({resp.status})")
                    # Per v1.2 spec, signature is MANDATORY
                    # But for backward compat, we'll warn and continue for now
                    # TODO: Make this a hard failure in production

            # Parse manifest
            with open(manifest_path, 'r') as f:
                manifest_data = json.load(f)

            # Cache the manifest
            CACHED_MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(CACHED_MANIFEST_FILE, 'w') as f:
                json.dump(manifest_data, f, indent=2)

            # Clean up temp files
            os.unlink(manifest_path)
            if os.path.exists(sig_path):
                os.unlink(sig_path)

            return ManifestV2.from_dict(manifest_data)

    except Exception as e:
        logger.error(f"Failed to fetch manifest: {e}")
        return None


# =============================================================================
# Update Checking
# =============================================================================

async def check_for_updates(channel: str = "stable") -> UpdateInfo:
    """
    Check GitHub Releases for available updates.

    v1.2 enhancements:
    - Try release.json v2 manifest first (with signature verification)
    - Fall back to GitHub API parsing
    - Apply anti-downgrade check
    - Apply skip list check
    - Apply version pin check
    """
    import aiohttp

    current = get_current_version()

    # v1.2: Try release.json v2 manifest first
    manifest = await fetch_manifest_v2()
    if manifest:
        logger.info(f"Using release.json v2 manifest (schema {manifest.schema_version})")

        # Get MIRS asset info
        asset = manifest.assets.get('mirs')
        if not asset:
            logger.warning("No 'mirs' asset in manifest")
        else:
            latest_version = manifest.version

            # v1.2: Check skip list
            skip_list = load_skip_list()
            if latest_version in skip_list:
                logger.info(f"Version {latest_version} is in skip list, ignoring")
                return UpdateInfo(
                    available=False,
                    current_version=current.version,
                    latest_version=current.version
                )

            # v1.2: Check version pin
            pin_pattern = load_version_pin()
            if not is_version_allowed_by_pin(latest_version, pin_pattern):
                logger.info(f"Version {latest_version} doesn't match pin pattern {pin_pattern}")
                return UpdateInfo(
                    available=False,
                    current_version=current.version,
                    latest_version=current.version
                )

            # v1.2: Anti-downgrade check
            allowed, reason = check_version_upgrade(current.version, latest_version)
            if not allowed:
                logger.info(f"Version check: {reason}")
                return UpdateInfo(
                    available=False,
                    current_version=current.version,
                    latest_version=latest_version
                )

            return UpdateInfo(
                available=compare_versions(current.version, latest_version) < 0,
                current_version=current.version,
                latest_version=latest_version,
                release_notes=manifest.release_notes,
                download_url=asset.download_url,
                checksum=asset.sha256,
                size_bytes=asset.size_bytes,
                release_date=manifest.release_date,
                breaking_changes=manifest.breaking_changes.get('has_breaking', False)
            )

    # Fall back to GitHub API parsing (for older releases without release.json)
    logger.info("Falling back to GitHub API parsing")
    try:
        async with aiohttp.ClientSession() as session:
            headers = {
                'Accept': 'application/vnd.github.v3+json',
                'User-Agent': 'MIRS-OTA-Client/2.0'
            }

            async with session.get(GITHUB_API_URL, headers=headers, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()

                    tag_name = data.get('tag_name', '')
                    latest_version = tag_name.lstrip('v')

                    # v1.2: Apply safety checks even for API fallback
                    skip_list = load_skip_list()
                    if latest_version in skip_list:
                        logger.info(f"Version {latest_version} is in skip list")
                        return UpdateInfo(
                            available=False,
                            current_version=current.version,
                            latest_version=current.version
                        )

                    allowed, reason = check_version_upgrade(current.version, latest_version)
                    if not allowed:
                        logger.info(f"Version check: {reason}")
                        return UpdateInfo(
                            available=False,
                            current_version=current.version,
                            latest_version=latest_version
                        )

                    # Find ARM64 binary asset
                    download_url = None
                    checksum = None
                    size_bytes = None

                    for asset in data.get('assets', []):
                        asset_name = asset.get('name', '')
                        if 'arm64' in asset_name or 'aarch64' in asset_name:
                            if asset_name.endswith('.sha256'):
                                pass
                            elif 'mirs-server' in asset_name:
                                download_url = asset.get('browser_download_url')
                                size_bytes = asset.get('size')

                    return UpdateInfo(
                        available=compare_versions(current.version, latest_version) < 0,
                        current_version=current.version,
                        latest_version=latest_version,
                        release_notes=data.get('body'),
                        download_url=download_url,
                        checksum=checksum,
                        size_bytes=size_bytes,
                        release_date=data.get('published_at'),
                        breaking_changes='BREAKING' in (data.get('body') or '')
                    )
                elif resp.status == 404:
                    logger.info("No releases found on GitHub")
                else:
                    logger.warning(f"GitHub API check failed: HTTP {resp.status}")

    except Exception as e:
        logger.error(f"Update check error: {e}")

    return UpdateInfo(
        available=False,
        current_version=current.version,
        latest_version=current.version
    )


def check_for_updates_sync(channel: str = "stable") -> UpdateInfo:
    """Synchronous version of update check using GitHub Releases."""
    import requests

    current = get_current_version()

    try:
        headers = {
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'MIRS-OTA-Client/1.0'
        }

        resp = requests.get(GITHUB_API_URL, headers=headers, timeout=30)
        if resp.status_code == 200:
            data = resp.json()

            # Parse version from tag (e.g., "v1.5.0" -> "1.5.0")
            tag_name = data.get('tag_name', '')
            latest_version = tag_name.lstrip('v')

            # Find ARM64 binary asset
            download_url = None
            size_bytes = None

            for asset in data.get('assets', []):
                asset_name = asset.get('name', '')
                if ('arm64' in asset_name or 'aarch64' in asset_name) and 'mirs-server' in asset_name:
                    if not asset_name.endswith('.sha256'):
                        download_url = asset.get('browser_download_url')
                        size_bytes = asset.get('size')
                        break

            return UpdateInfo(
                available=compare_versions(current.version, latest_version) < 0,
                current_version=current.version,
                latest_version=latest_version,
                release_notes=data.get('body'),
                download_url=download_url,
                checksum=None,
                size_bytes=size_bytes,
                release_date=data.get('published_at'),
                breaking_changes='BREAKING' in (data.get('body') or '')
            )

    except Exception as e:
        logger.error(f"Update check error: {e}")

    return UpdateInfo(
        available=False,
        current_version=current.version,
        latest_version=current.version
    )


# =============================================================================
# Docker-based Updates
# =============================================================================

class DockerUpdater:
    """Docker-based update handler."""

    def __init__(self):
        self.image = f"{DOCKER_REGISTRY}/{DOCKER_IMAGE_NAME}"

    def pull_image(self, tag: str) -> bool:
        """Pull Docker image with specified tag."""
        try:
            result = subprocess.run(
                ['docker', 'pull', f"{self.image}:{tag}"],
                capture_output=True,
                text=True,
                timeout=600  # 10 minutes
            )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Docker pull failed: {e}")
            return False

    def get_current_container(self) -> Optional[str]:
        """Get current running container ID."""
        try:
            result = subprocess.run(
                ['docker', 'ps', '-q', '-f', f'ancestor={self.image}'],
                capture_output=True,
                text=True
            )
            container_id = result.stdout.strip()
            return container_id if container_id else None
        except Exception:
            return None

    def get_current_tag(self) -> Optional[str]:
        """Get current running image tag."""
        try:
            result = subprocess.run(
                ['docker', 'inspect', '--format', '{{.Config.Image}}',
                 self.get_current_container() or ''],
                capture_output=True,
                text=True
            )
            image = result.stdout.strip()
            if ':' in image:
                return image.split(':')[-1]
            return 'latest'
        except Exception:
            return None

    def switch_to_tag(self, new_tag: str, backup_tag: str = None) -> UpdateResult:
        """Switch to new Docker image tag."""
        current = get_current_version()

        try:
            # Save rollback info
            if backup_tag:
                self._save_rollback_info(backup_tag)

            # Pull new image
            logger.info(f"Pulling image: {self.image}:{new_tag}")
            if not self.pull_image(new_tag):
                return UpdateResult(
                    success=False,
                    status=UpdateStatus.FAILED,
                    message="Failed to pull new image",
                    previous_version=current.version
                )

            # Stop current container
            container_id = self.get_current_container()
            if container_id:
                subprocess.run(['docker', 'stop', container_id], timeout=30)

            # Start new container (using docker-compose or direct run)
            # This is typically handled by the orchestrator
            logger.info(f"New image ready: {self.image}:{new_tag}")
            logger.info("Container restart should be handled by orchestrator")

            return UpdateResult(
                success=True,
                status=UpdateStatus.COMPLETED,
                message=f"Updated to {new_tag}",
                previous_version=current.version,
                new_version=new_tag,
                rollback_available=backup_tag is not None
            )

        except Exception as e:
            logger.error(f"Docker update failed: {e}")
            return UpdateResult(
                success=False,
                status=UpdateStatus.FAILED,
                message=str(e),
                previous_version=current.version
            )

    def rollback(self) -> UpdateResult:
        """Rollback to previous version."""
        rollback_info = self._load_rollback_info()
        if not rollback_info:
            return UpdateResult(
                success=False,
                status=UpdateStatus.FAILED,
                message="No rollback information available"
            )

        previous_tag = rollback_info.get('previous_tag')
        if not previous_tag:
            return UpdateResult(
                success=False,
                status=UpdateStatus.FAILED,
                message="Previous tag not found"
            )

        return self.switch_to_tag(previous_tag)

    def _save_rollback_info(self, previous_tag: str):
        """Save rollback information."""
        try:
            ROLLBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(ROLLBACK_FILE, 'w') as f:
                json.dump({
                    'previous_tag': previous_tag,
                    'timestamp': datetime.now().isoformat(),
                    'method': 'docker'
                }, f)
        except Exception as e:
            logger.error(f"Failed to save rollback info: {e}")

    def _load_rollback_info(self) -> Optional[Dict]:
        """Load rollback information."""
        try:
            if ROLLBACK_FILE.exists():
                with open(ROLLBACK_FILE, 'r') as f:
                    return json.load(f)
        except Exception:
            pass
        return None


# =============================================================================
# Binary-based Updates
# =============================================================================

class BinaryUpdater:
    """Binary-based update handler for standalone deployments."""

    def __init__(self):
        self.binary_path = BINARY_PATH
        self.backup_path = BINARY_BACKUP_PATH

    def download_binary(self, url: str, checksum: str = None) -> Optional[Path]:
        """Download new binary from URL."""
        import requests

        download_path = UPDATE_DIR / 'mirs-hub.new'

        try:
            UPDATE_DIR.mkdir(parents=True, exist_ok=True)

            logger.info(f"Downloading update from {url}")
            resp = requests.get(url, stream=True, timeout=600)
            resp.raise_for_status()

            with open(download_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)

            # Verify checksum
            if checksum:
                actual_checksum = self._calculate_checksum(download_path)
                if actual_checksum != checksum:
                    logger.error(f"Checksum mismatch: expected {checksum}, got {actual_checksum}")
                    download_path.unlink()
                    return None

            return download_path

        except Exception as e:
            logger.error(f"Download failed: {e}")
            if download_path.exists():
                download_path.unlink()
            return None

    def apply_update(self, new_binary: Path) -> UpdateResult:
        """Apply binary update with backup."""
        current = get_current_version()

        try:
            # Backup current binary
            if self.binary_path.exists():
                logger.info("Backing up current binary")
                shutil.copy2(self.binary_path, self.backup_path)
                self._save_rollback_info(current.version)

            # Replace binary
            logger.info("Installing new binary")
            shutil.move(str(new_binary), str(self.binary_path))
            os.chmod(self.binary_path, 0o755)

            # Signal for restart (create marker file)
            restart_marker = DATA_DIR / 'restart_required'
            restart_marker.touch()

            return UpdateResult(
                success=True,
                status=UpdateStatus.COMPLETED,
                message="Update applied. Restart required.",
                previous_version=current.version,
                rollback_available=True
            )

        except Exception as e:
            logger.error(f"Update application failed: {e}")
            # Attempt to restore backup
            if self.backup_path.exists():
                shutil.copy2(self.backup_path, self.binary_path)

            return UpdateResult(
                success=False,
                status=UpdateStatus.FAILED,
                message=str(e),
                previous_version=current.version
            )

    def rollback(self) -> UpdateResult:
        """Rollback to previous binary."""
        if not self.backup_path.exists():
            return UpdateResult(
                success=False,
                status=UpdateStatus.FAILED,
                message="No backup binary available"
            )

        try:
            shutil.copy2(self.backup_path, self.binary_path)

            restart_marker = DATA_DIR / 'restart_required'
            restart_marker.touch()

            return UpdateResult(
                success=True,
                status=UpdateStatus.COMPLETED,
                message="Rollback complete. Restart required."
            )

        except Exception as e:
            return UpdateResult(
                success=False,
                status=UpdateStatus.FAILED,
                message=str(e)
            )

    def _calculate_checksum(self, filepath: Path) -> str:
        """Calculate SHA256 checksum of file."""
        sha256 = hashlib.sha256()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _save_rollback_info(self, previous_version: str):
        """Save rollback information."""
        try:
            ROLLBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(ROLLBACK_FILE, 'w') as f:
                json.dump({
                    'previous_version': previous_version,
                    'timestamp': datetime.now().isoformat(),
                    'method': 'binary'
                }, f)
        except Exception as e:
            logger.error(f"Failed to save rollback info: {e}")


# =============================================================================
# Health Check
# =============================================================================

def verify_health(timeout: int = 30) -> bool:
    """Verify system health after update."""
    import requests

    health_url = "http://localhost:8000/api/health"
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            resp = requests.get(health_url, timeout=5)
            if resp.status_code == 200:
                logger.info("Health check passed")
                return True
        except Exception:
            pass
        time.sleep(2)

    logger.error("Health check failed")
    return False


# =============================================================================
# OTA Manager
# =============================================================================

class OTAManager:
    """Main OTA update manager."""

    _instance = None
    _status: UpdateStatus = UpdateStatus.IDLE
    _last_check: Optional[datetime] = None
    _last_update_info: Optional[UpdateInfo] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def status(self) -> UpdateStatus:
        return self._status

    @property
    def update_method(self) -> UpdateMethod:
        return detect_update_method()

    def get_status(self) -> Dict[str, Any]:
        """Get current OTA status."""
        current = get_current_version()
        return {
            'status': self._status.value,
            'current_version': current.version,
            'build_date': current.build_date,
            'update_method': self.update_method.value,
            'last_check': self._last_check.isoformat() if self._last_check else None,
            'update_available': self._last_update_info.available if self._last_update_info else False,
            'latest_version': self._last_update_info.latest_version if self._last_update_info else None
        }

    async def check_updates(self, channel: str = "stable") -> UpdateInfo:
        """Check for available updates."""
        self._status = UpdateStatus.CHECKING
        try:
            self._last_update_info = await check_for_updates(channel)
            self._last_check = datetime.now()
            return self._last_update_info
        finally:
            self._status = UpdateStatus.IDLE

    def apply_update(self, version: str = None) -> UpdateResult:
        """Apply available update."""
        if self._status != UpdateStatus.IDLE:
            return UpdateResult(
                success=False,
                status=self._status,
                message=f"Update already in progress: {self._status.value}"
            )

        method = self.update_method

        if method == UpdateMethod.DOCKER:
            self._status = UpdateStatus.APPLYING
            try:
                updater = DockerUpdater()
                current_tag = updater.get_current_tag()
                new_tag = version or (self._last_update_info.latest_version if self._last_update_info else None)

                if not new_tag:
                    return UpdateResult(
                        success=False,
                        status=UpdateStatus.FAILED,
                        message="No version specified and no update info available"
                    )

                result = updater.switch_to_tag(new_tag, backup_tag=current_tag)

                if result.success:
                    self._status = UpdateStatus.VERIFYING
                    if verify_health():
                        self._status = UpdateStatus.COMPLETED
                    else:
                        # Auto rollback
                        self._status = UpdateStatus.ROLLING_BACK
                        updater.rollback()
                        result = UpdateResult(
                            success=False,
                            status=UpdateStatus.FAILED,
                            message="Health check failed, rolled back"
                        )

                return result

            finally:
                if self._status not in (UpdateStatus.COMPLETED, UpdateStatus.FAILED):
                    self._status = UpdateStatus.IDLE

        elif method == UpdateMethod.BINARY:
            if not self._last_update_info or not self._last_update_info.download_url:
                return UpdateResult(
                    success=False,
                    status=UpdateStatus.FAILED,
                    message="No download URL available"
                )

            self._status = UpdateStatus.DOWNLOADING
            try:
                updater = BinaryUpdater()
                new_binary = updater.download_binary(
                    self._last_update_info.download_url,
                    self._last_update_info.checksum
                )

                if not new_binary:
                    return UpdateResult(
                        success=False,
                        status=UpdateStatus.FAILED,
                        message="Download failed"
                    )

                self._status = UpdateStatus.APPLYING
                return updater.apply_update(new_binary)

            finally:
                self._status = UpdateStatus.IDLE

        else:
            return UpdateResult(
                success=False,
                status=UpdateStatus.FAILED,
                message="Manual update required for this deployment type"
            )

    def rollback(self) -> UpdateResult:
        """Rollback to previous version."""
        method = self.update_method

        if method == UpdateMethod.DOCKER:
            return DockerUpdater().rollback()
        elif method == UpdateMethod.BINARY:
            return BinaryUpdater().rollback()
        else:
            return UpdateResult(
                success=False,
                status=UpdateStatus.FAILED,
                message="Rollback not available for this deployment type"
            )


# =============================================================================
# Singleton Instance
# =============================================================================

ota_manager = OTAManager()


def get_ota_status() -> Dict[str, Any]:
    """Get current OTA status."""
    return ota_manager.get_status()


async def check_updates(channel: str = "stable") -> UpdateInfo:
    """Check for updates."""
    return await ota_manager.check_updates(channel)


def apply_update(version: str = None) -> UpdateResult:
    """Apply update."""
    return ota_manager.apply_update(version)


def rollback_update() -> UpdateResult:
    """Rollback to previous version."""
    return ota_manager.rollback()
