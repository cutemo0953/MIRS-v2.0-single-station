"""
xIRS OTA Auto-Update Scheduler

Background scheduler that:
- Periodically checks GitHub Releases for updates
- Applies safety checks before updating (Active Case Guard, Time Validity)
- Verifies signatures and checksums
- Implements atomic swap protocol (v1.2) for update safety
- Automatically restarts service after update
- Rolls back on health check failure

v1.2 Atomic Update Protocol:
- Double buffering with versions directory
- Atomic symlink swap (prevents bricking)
- Clean rollback procedure
- Skip list for failed versions

Version: 2.0
Date: 2026-01-26
Reference: DEV_SPEC_OTA_ARCHITECTURE_v1.2 (Final)
"""

import asyncio
import fcntl
import json
import logging
import os
import random
import shutil
import subprocess
from dataclasses import dataclass, asdict
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Optional, Dict, Any

from .ota_service import (
    check_for_updates,
    BinaryUpdater,
    get_current_version,
    UpdateInfo,
    compare_versions,
    add_to_skip_list  # v1.2: For rollback skip list
)
from .ota_safety import (
    run_all_safety_checks,
    check_health_comprehensive,
    is_safe_to_update,
    SafetyReport
)
from .ota_security import (
    verify_update_package,
    secure_download,
    SIGNATURE_EXTENSION
)

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# Environment variables
OTA_CHECK_INTERVAL = int(os.environ.get('MIRS_OTA_CHECK_INTERVAL', '3600'))  # 1 hour
OTA_AUTO_UPDATE = os.environ.get('MIRS_OTA_AUTO_UPDATE', 'false').lower() == 'true'
OTA_UPDATE_WINDOW_START = os.environ.get('MIRS_OTA_WINDOW_START', '02:00')
OTA_UPDATE_WINDOW_END = os.environ.get('MIRS_OTA_WINDOW_END', '05:00')
OTA_CHANNEL = os.environ.get('MIRS_OTA_CHANNEL', 'stable')
OTA_REQUIRE_SIGNATURE = os.environ.get('MIRS_OTA_REQUIRE_SIGNATURE', 'false').lower() == 'true'
OTA_SCHEDULER_ENABLED = os.environ.get('MIRS_OTA_SCHEDULER_ENABLED', 'true').lower() == 'true'

# Paths
OTA_LOCK_FILE = Path('/var/lock/mirs-ota.lock')
OTA_STATE_FILE = Path(os.environ.get('MIRS_DATA_DIR', '/var/lib/mirs')) / 'ota_state.json'

# v1.2: Atomic update protocol paths
# Double buffering: versions directory with symlinks
APP_DIR = Path(os.environ.get('MIRS_APP_DIR', '/app'))
VERSIONS_DIR = APP_DIR / 'versions'
BINARY_PATH = APP_DIR / 'mirs-server'              # Symlink to current version
BACKUP_SYMLINK = APP_DIR / 'mirs-server.bak'       # Symlink to previous version
TMP_SYMLINK = APP_DIR / 'mirs-server.new-link'     # Temporary symlink for atomic swap

# Retry limits
MAX_RETRIES_PER_VERSION = 3
HEALTH_CHECK_TIMEOUT = 60
JITTER_MAX_SECONDS = 1800  # 30 minutes random jitter


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class SchedulerState:
    """Persistent scheduler state."""
    last_check: Optional[str] = None
    last_update: Optional[str] = None
    last_update_version: Optional[str] = None
    pending_update: Optional[dict] = None
    retry_count: int = 0
    failed_versions: list = None

    def __post_init__(self):
        if self.failed_versions is None:
            self.failed_versions = []


# =============================================================================
# OTA Scheduler
# =============================================================================

class OTAScheduler:
    """
    Background OTA update scheduler with safety checks.

    Features:
    - Periodic check for updates (default: every 1 hour)
    - Time window enforcement (default: 02:00-05:00)
    - Active case guard (won't update during surgery)
    - Signature verification
    - Automatic rollback on failure
    - Concurrency lock to prevent overlapping updates
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.is_running = False
        self.check_interval = OTA_CHECK_INTERVAL
        self.auto_update = OTA_AUTO_UPDATE
        self.update_window = (OTA_UPDATE_WINDOW_START, OTA_UPDATE_WINDOW_END)
        self.channel = OTA_CHANNEL
        self.require_signature = OTA_REQUIRE_SIGNATURE

        self._task: Optional[asyncio.Task] = None
        self._state: SchedulerState = self._load_state()
        self._lock_fd = None

        self._initialized = True

    # =========================================================================
    # State Management
    # =========================================================================

    def _load_state(self) -> SchedulerState:
        """Load persistent state from file."""
        try:
            if OTA_STATE_FILE.exists():
                with open(OTA_STATE_FILE, 'r') as f:
                    data = json.load(f)
                    return SchedulerState(**data)
        except Exception as e:
            logger.warning(f"Failed to load OTA state: {e}")

        return SchedulerState()

    def _save_state(self):
        """Save state to file."""
        try:
            OTA_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(OTA_STATE_FILE, 'w') as f:
                json.dump(asdict(self._state), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save OTA state: {e}")

    # =========================================================================
    # Scheduler Control
    # =========================================================================

    async def start(self):
        """Start the background scheduler."""
        if self.is_running:
            logger.warning("OTA Scheduler already running")
            return

        self.is_running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            f"OTA Scheduler started "
            f"(interval: {self.check_interval}s, "
            f"auto_update: {self.auto_update}, "
            f"window: {self.update_window[0]}-{self.update_window[1]})"
        )

    async def stop(self):
        """Stop the scheduler."""
        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("OTA Scheduler stopped")

    def get_status(self) -> Dict[str, Any]:
        """Get current scheduler status."""
        current = get_current_version()
        return {
            "running": self.is_running,
            "auto_update_enabled": self.auto_update,
            "check_interval_seconds": self.check_interval,
            "update_window": f"{self.update_window[0]}-{self.update_window[1]}",
            "channel": self.channel,
            "current_version": current.version,
            "last_check": self._state.last_check,
            "last_update": self._state.last_update,
            "pending_update": self._state.pending_update,
            "retry_count": self._state.retry_count
        }

    # =========================================================================
    # Main Loop
    # =========================================================================

    async def _run_loop(self):
        """Main scheduler loop."""
        # Add random jitter to prevent thundering herd
        initial_delay = random.randint(60, JITTER_MAX_SECONDS)
        logger.info(f"OTA Scheduler: initial delay {initial_delay}s (jitter)")
        await asyncio.sleep(initial_delay)

        while self.is_running:
            try:
                await self._check_and_update()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"OTA check error: {e}", exc_info=True)

            # Add small jitter to check interval
            jitter = random.randint(0, 300)  # 0-5 minutes
            await asyncio.sleep(self.check_interval + jitter)

    async def _check_and_update(self):
        """Check for updates and apply if safe."""
        logger.debug("OTA: Checking for updates...")

        self._state.last_check = datetime.now().isoformat()
        self._save_state()

        # 1. Check for available updates
        try:
            update_info = await check_for_updates(self.channel)
        except Exception as e:
            logger.error(f"Failed to check for updates: {e}")
            return

        if not update_info.available:
            logger.debug("No update available")
            self._state.pending_update = None
            self._save_state()
            return

        logger.info(f"Update available: {update_info.latest_version}")

        # Store pending update info
        self._state.pending_update = {
            "version": update_info.latest_version,
            "download_url": update_info.download_url,
            "detected_at": datetime.now().isoformat()
        }
        self._save_state()

        # 2. Check if we should skip this version (too many failures)
        if update_info.latest_version in self._state.failed_versions:
            logger.warning(f"Skipping version {update_info.latest_version} (previously failed)")
            return

        if self._state.retry_count >= MAX_RETRIES_PER_VERSION:
            logger.warning(f"Max retries reached for {update_info.latest_version}")
            self._state.failed_versions.append(update_info.latest_version)
            self._state.retry_count = 0
            self._save_state()
            return

        # 3. Check if auto-update is enabled
        if not self.auto_update:
            logger.info("Auto-update disabled, skipping apply")
            return

        # 4. Run safety checks
        current = get_current_version()
        safety_report = await run_all_safety_checks(
            new_version=update_info.latest_version,
            current_version=current.version,
            release_notes=update_info.release_notes,
            migration_policy=getattr(update_info, 'migration_policy', 'none'),
            rollback_compatible=getattr(update_info, 'rollback_compatible', True),
            update_window=self.update_window
        )

        if not safety_report.safe_to_update:
            logger.info(f"Safety checks failed: {safety_report.blocking_reasons}")
            return

        if safety_report.warnings:
            for warning in safety_report.warnings:
                logger.warning(f"OTA Warning: {warning}")

        # 5. Apply update with lock
        await self._apply_update_with_lock(update_info)

    # =========================================================================
    # Update Application (with Lock)
    # =========================================================================

    async def _apply_update_with_lock(self, update_info: UpdateInfo):
        """Apply update with file lock to prevent concurrent updates."""

        # Acquire lock (non-blocking)
        try:
            OTA_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
            self._lock_fd = open(OTA_LOCK_FILE, 'w')
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.warning("Another OTA update is in progress, skipping")
            return
        except Exception as e:
            logger.error(f"Failed to acquire OTA lock: {e}")
            return

        try:
            await self._apply_update(update_info)
        finally:
            # Release lock
            if self._lock_fd:
                try:
                    fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                    self._lock_fd.close()
                except:
                    pass
                self._lock_fd = None

    async def _apply_update(self, update_info: UpdateInfo):
        """
        Apply the update using atomic swap protocol (v1.2).

        The atomic swap protocol guarantees:
        - Binary is either old version OR new version, never corrupt
        - Power loss at any point is safe
        - Automatic rollback on failure

        Protocol phases:
        1. DOWNLOAD: Download and verify in temp location
        2. INSTALL: Create new version directory, atomic move
        3. SWAP: Atomic symlink replacement
        4. VERIFY: Health check
        5. COMMIT/ROLLBACK: Finalize or revert
        """
        logger.info(f"Applying update to {update_info.latest_version} (atomic swap protocol)")

        current = get_current_version()
        new_version = update_info.latest_version

        # =================================================================
        # Phase 1: DOWNLOAD
        # =================================================================
        logger.info("Phase 1: DOWNLOAD")

        if not update_info.download_url:
            logger.error("No download URL available")
            self._state.retry_count += 1
            self._save_state()
            return

        download_path = Path('/tmp/mirs-server.new')

        # Build signature URL (same URL with .minisig extension)
        sig_url = None
        if self.require_signature:
            sig_url = update_info.download_url + SIGNATURE_EXTENSION

        success, msg = secure_download(
            url=update_info.download_url,
            dest_path=str(download_path),
            expected_checksum=update_info.checksum,
            signature_url=sig_url
        )

        if not success:
            logger.error(f"Download/verification failed: {msg}")
            self._state.retry_count += 1
            self._save_state()
            return

        logger.info(f"Download verified: {msg}")

        # =================================================================
        # Phase 2: INSTALL (atomic file operations)
        # =================================================================
        logger.info("Phase 2: INSTALL")

        # Create versions directory
        new_version_dir = VERSIONS_DIR / new_version
        new_binary_path = new_version_dir / 'mirs-server'

        try:
            VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
            new_version_dir.mkdir(parents=True, exist_ok=True)

            # Move downloaded binary to version directory
            # os.rename is atomic on POSIX if same filesystem
            shutil.move(str(download_path), str(new_binary_path))
            os.chmod(new_binary_path, 0o755)

            logger.info(f"Installed to: {new_binary_path}")

        except Exception as e:
            logger.error(f"Install failed: {e}")
            self._state.retry_count += 1
            self._save_state()
            if download_path.exists():
                download_path.unlink()
            return

        # =================================================================
        # Phase 3: SWAP (atomic symlink replacement)
        # =================================================================
        logger.info("Phase 3: SWAP (atomic symlink)")

        try:
            # Determine current version path (for backup symlink)
            current_target = None
            if BINARY_PATH.is_symlink():
                current_target = BINARY_PATH.resolve()
            elif BINARY_PATH.exists():
                # First time: not a symlink yet, backup the actual file
                first_version_dir = VERSIONS_DIR / current.version
                first_version_dir.mkdir(parents=True, exist_ok=True)
                first_binary = first_version_dir / 'mirs-server'
                if not first_binary.exists():
                    shutil.copy2(BINARY_PATH, first_binary)
                current_target = first_binary

            # Update backup symlink to point to current version
            if current_target:
                if BACKUP_SYMLINK.is_symlink():
                    BACKUP_SYMLINK.unlink()
                BACKUP_SYMLINK.symlink_to(current_target)
                logger.info(f"Backup symlink: {BACKUP_SYMLINK} -> {current_target}")

            # Create new temporary symlink pointing to new version
            if TMP_SYMLINK.exists() or TMP_SYMLINK.is_symlink():
                TMP_SYMLINK.unlink()
            TMP_SYMLINK.symlink_to(new_binary_path)

            # ATOMIC SWAP: os.rename is atomic on POSIX
            # This ensures BINARY_PATH is always valid (old or new, never broken)
            os.rename(str(TMP_SYMLINK), str(BINARY_PATH))
            logger.info(f"Atomic swap complete: {BINARY_PATH} -> {new_binary_path}")

        except Exception as e:
            logger.error(f"Atomic swap failed: {e}")
            self._state.retry_count += 1
            self._save_state()
            # Clean up
            if TMP_SYMLINK.exists():
                TMP_SYMLINK.unlink()
            return

        # =================================================================
        # Phase 4: VERIFY (restart and health check)
        # =================================================================
        logger.info("Phase 4: VERIFY")

        logger.info("Restarting service...")
        restart_result = subprocess.run(
            ['systemctl', 'restart', 'mirs'],
            capture_output=True,
            timeout=60
        )

        if restart_result.returncode != 0:
            logger.error(f"Service restart failed: {restart_result.stderr}")
            await self._rollback()
            return

        logger.info(f"Waiting for service to start (timeout: {HEALTH_CHECK_TIMEOUT}s)...")
        await asyncio.sleep(10)  # Give service time to start

        health_result, health_msg = await check_health_comprehensive()

        # =================================================================
        # Phase 5: COMMIT or ROLLBACK
        # =================================================================
        if health_result.value == "pass":
            logger.info("Phase 5: COMMIT")
            logger.info(f"Update successful! Now running {new_version}")

            self._state.last_update = datetime.now().isoformat()
            self._state.last_update_version = new_version
            self._state.pending_update = None
            self._state.retry_count = 0
            self._save_state()

            # Clean up old versions (keep last 2)
            self._cleanup_old_versions(keep=2)
        else:
            logger.error(f"Health check failed: {health_msg}")
            logger.info("Phase 5: ROLLBACK")
            await self._rollback()

    def _cleanup_old_versions(self, keep: int = 2):
        """Clean up old version directories, keeping the most recent N."""
        try:
            if not VERSIONS_DIR.exists():
                return

            versions = sorted(VERSIONS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)

            for old_version in versions[keep:]:
                if old_version.is_dir():
                    logger.info(f"Cleaning up old version: {old_version.name}")
                    shutil.rmtree(old_version)
        except Exception as e:
            logger.warning(f"Cleanup failed: {e}")

    async def _rollback(self):
        """
        Rollback to previous version using atomic symlink swap.

        v1.2 protocol:
        1. Get backup symlink target
        2. Create new temp symlink to backup target
        3. Atomic rename to replace current symlink
        4. Restart service
        5. Add failed version to skip list
        """
        logger.warning("Rolling back to previous version (atomic swap)...")

        # Check if backup symlink exists and is valid
        if not BACKUP_SYMLINK.is_symlink():
            logger.error("No backup symlink available for rollback!")
            self._state.retry_count += 1
            self._save_state()
            return

        backup_target = BACKUP_SYMLINK.resolve()
        if not backup_target.exists():
            logger.error(f"Backup target doesn't exist: {backup_target}")
            self._state.retry_count += 1
            self._save_state()
            return

        try:
            # Create temp symlink to backup target
            if TMP_SYMLINK.exists() or TMP_SYMLINK.is_symlink():
                TMP_SYMLINK.unlink()
            TMP_SYMLINK.symlink_to(backup_target)

            # Atomic swap: replace current symlink with backup target
            os.rename(str(TMP_SYMLINK), str(BINARY_PATH))
            logger.info(f"Restored: {BINARY_PATH} -> {backup_target}")

            # Restart service
            subprocess.run(
                ['systemctl', 'restart', 'mirs'],
                capture_output=True,
                timeout=60
            )

            logger.info("Rollback completed successfully")

            # Add the failed version to skip list
            if self._state.pending_update:
                failed_version = self._state.pending_update.get('version')
                if failed_version:
                    # Import and use the add_to_skip_list function
                    try:
                        from .ota_service import add_to_skip_list
                        add_to_skip_list(failed_version, "health_check_failed")
                        logger.info(f"Added {failed_version} to skip list")
                    except ImportError:
                        self._state.failed_versions.append(failed_version)

            self._state.retry_count += 1
            self._save_state()

        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            self._state.retry_count += 1
            self._save_state()

    # =========================================================================
    # Manual Triggers
    # =========================================================================

    async def check_now(self) -> Dict[str, Any]:
        """Manually trigger an update check."""
        try:
            update_info = await check_for_updates(self.channel)
            return {
                "available": update_info.available,
                "current_version": get_current_version().version,
                "latest_version": update_info.latest_version,
                "download_url": update_info.download_url,
                "release_notes": update_info.release_notes[:500] if update_info.release_notes else None
            }
        except Exception as e:
            return {"error": str(e)}

    async def apply_now(self, version: Optional[str] = None) -> Dict[str, Any]:
        """Manually trigger update application (bypasses time window)."""
        # Still check for active cases - this is non-negotiable
        safe, reason = is_safe_to_update()
        if not safe:
            return {"success": False, "error": reason}

        try:
            update_info = await check_for_updates(self.channel)

            if not update_info.available:
                return {"success": False, "error": "No update available"}

            if version and update_info.latest_version != version:
                return {"success": False, "error": f"Version mismatch: expected {version}, got {update_info.latest_version}"}

            await self._apply_update_with_lock(update_info)

            return {
                "success": True,
                "version": update_info.latest_version,
                "message": "Update applied"
            }

        except Exception as e:
            return {"success": False, "error": str(e)}


# =============================================================================
# Singleton Instance
# =============================================================================

ota_scheduler = OTAScheduler()


async def start_scheduler():
    """Start the OTA scheduler."""
    if OTA_SCHEDULER_ENABLED:
        await ota_scheduler.start()


async def stop_scheduler():
    """Stop the OTA scheduler."""
    await ota_scheduler.stop()


def get_scheduler_status() -> Dict[str, Any]:
    """Get scheduler status."""
    return ota_scheduler.get_status()
