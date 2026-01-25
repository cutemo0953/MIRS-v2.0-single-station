"""
xIRS OTA (Over-The-Air) Update Service

Implements:
- Version checking against update server
- Docker-based updates with tag switching
- Binary-based updates for standalone deployments
- Automatic rollback on failure
- Health check verification

Version: 1.0
Date: 2026-01-25
Reference: DEV_SPEC_COMMERCIAL_APPLIANCE_v1.6 (P1-04)
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
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# Update server (can be overridden by environment)
UPDATE_SERVER = os.environ.get('MIRS_UPDATE_SERVER', 'https://updates.xirs.io')
UPDATE_CHECK_INTERVAL = 3600  # 1 hour

# Docker configuration
DOCKER_REGISTRY = os.environ.get('MIRS_DOCKER_REGISTRY', 'ghcr.io/xirs')
DOCKER_IMAGE_NAME = 'mirs-hub'

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
# Update Checking
# =============================================================================

async def check_for_updates(channel: str = "stable") -> UpdateInfo:
    """Check update server for available updates."""
    import aiohttp

    current = get_current_version()

    try:
        async with aiohttp.ClientSession() as session:
            url = f"{UPDATE_SERVER}/api/v1/updates/{channel}/latest"
            params = {
                'current_version': current.version,
                'platform': 'arm64',
                'product': 'mirs-hub'
            }

            async with session.get(url, params=params, timeout=30) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    latest_version = data.get('version', current.version)

                    return UpdateInfo(
                        available=compare_versions(current.version, latest_version) < 0,
                        current_version=current.version,
                        latest_version=latest_version,
                        release_notes=data.get('release_notes'),
                        download_url=data.get('download_url'),
                        checksum=data.get('checksum'),
                        size_bytes=data.get('size_bytes'),
                        release_date=data.get('release_date'),
                        breaking_changes=data.get('breaking_changes', False)
                    )
                elif resp.status == 204:
                    # No update available
                    return UpdateInfo(
                        available=False,
                        current_version=current.version,
                        latest_version=current.version
                    )
                else:
                    logger.warning(f"Update check failed: HTTP {resp.status}")

    except Exception as e:
        logger.error(f"Update check error: {e}")

    # Return no-update on error
    return UpdateInfo(
        available=False,
        current_version=current.version,
        latest_version=current.version
    )


def check_for_updates_sync(channel: str = "stable") -> UpdateInfo:
    """Synchronous version of update check."""
    import requests

    current = get_current_version()

    try:
        url = f"{UPDATE_SERVER}/api/v1/updates/{channel}/latest"
        params = {
            'current_version': current.version,
            'platform': 'arm64',
            'product': 'mirs-hub'
        }

        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            latest_version = data.get('version', current.version)

            return UpdateInfo(
                available=compare_versions(current.version, latest_version) < 0,
                current_version=current.version,
                latest_version=latest_version,
                release_notes=data.get('release_notes'),
                download_url=data.get('download_url'),
                checksum=data.get('checksum'),
                size_bytes=data.get('size_bytes'),
                release_date=data.get('release_date'),
                breaking_changes=data.get('breaking_changes', False)
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
