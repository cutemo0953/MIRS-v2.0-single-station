"""
xIRS License Management Service (Simplified for MIRS)

Implements:
- License State Machine (LICENSED, GRACE_MODE, BASIC_MODE, TRIAL)
- 72-hour Grace Period for hardware changes
- Watermark text generation

Version: 1.0
Date: 2026-01-25
Reference: DEV_SPEC_COMMERCIAL_APPLIANCE_v1.4
"""

import hashlib
import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

# ============================================================================
# Constants
# ============================================================================

GRACE_PERIOD_HOURS = 72
LICENSE_FILE = '/boot/license.key'  # RPi location
GRACE_FILE = '/var/lib/mirs/grace_started.txt'

# Fallback paths for development
if not os.path.exists('/boot'):
    LICENSE_FILE = os.path.expanduser('~/.mirs/license.key')
    GRACE_FILE = os.path.expanduser('~/.mirs/grace_started.txt')


# ============================================================================
# Enums and Data Classes
# ============================================================================

class LicenseState(Enum):
    """License state machine states."""
    LICENSED = "LICENSED"        # Fully licensed
    GRACE_MODE = "GRACE_MODE"    # Hardware mismatch, 72hr grace
    BASIC_MODE = "BASIC_MODE"    # Degraded mode (still functional)
    TRIAL = "TRIAL"              # Trial version


@dataclass
class LicenseStatus:
    """Current license status."""
    state: LicenseState
    tier: str
    expires_at: Optional[datetime]
    hardware_mismatch: bool
    grace_ends_at: Optional[datetime]
    message: str
    watermark_text: Optional[str]  # Text to show on PDF if not licensed


# ============================================================================
# Hardware ID Generation
# ============================================================================

def get_hardware_id() -> str:
    """
    Generate hardware fingerprint for license binding.
    Uses CPU serial (RPi) or MAC address (other platforms).
    """
    try:
        # Try RPi CPU serial first
        with open('/proc/cpuinfo', 'r') as f:
            for line in f:
                if line.startswith('Serial'):
                    serial = line.split(':')[1].strip()
                    return hashlib.sha256(f"rpi:{serial}".encode()).hexdigest()[:32]
    except Exception:
        pass

    try:
        # macOS: use hardware UUID
        result = subprocess.run(
            ['system_profiler', 'SPHardwareDataType'],
            capture_output=True, text=True
        )
        for line in result.stdout.split('\n'):
            if 'Hardware UUID' in line:
                uuid = line.split(':')[1].strip()
                return hashlib.sha256(f"mac:{uuid}".encode()).hexdigest()[:32]
    except Exception:
        pass

    # Fallback: use hostname
    import socket
    hostname = socket.gethostname()
    return hashlib.sha256(f"host:{hostname}".encode()).hexdigest()[:32]


# ============================================================================
# License Manager
# ============================================================================

class LicenseManager:
    """Manages license state and validation."""

    _instance = None
    _cache: Optional[LicenseStatus] = None
    _cache_time: float = 0
    _cache_ttl: float = 300  # 5 minutes

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def get_status(self, force_refresh: bool = False) -> LicenseStatus:
        """Get current license status with caching."""
        now = time.time()
        if not force_refresh and self._cache and (now - self._cache_time) < self._cache_ttl:
            return self._cache

        status = self._validate_license()
        self._cache = status
        self._cache_time = now
        return status

    def _validate_license(self) -> LicenseStatus:
        """Validate license file and determine state."""
        hardware_id = get_hardware_id()

        # Check if license file exists
        license_path = Path(LICENSE_FILE)
        if not license_path.exists():
            return self._create_trial_status()

        try:
            with open(license_path, 'r') as f:
                license_data = json.load(f)
        except Exception as e:
            logger.warning(f"License file read error: {e}")
            return self._create_trial_status()

        # Check hardware binding
        licensed_hardware = license_data.get('hardware_id', '')
        hardware_mismatch = licensed_hardware != hardware_id

        # Check expiration
        expires_str = license_data.get('expires_at')
        expires_at = None
        is_expired = False
        if expires_str:
            try:
                expires_at = datetime.fromisoformat(expires_str)
                is_expired = datetime.now() > expires_at
            except Exception:
                pass

        tier = license_data.get('tier', 'standard')

        # Determine state
        if hardware_mismatch:
            return self._handle_hardware_mismatch(tier, expires_at)
        elif is_expired:
            return LicenseStatus(
                state=LicenseState.BASIC_MODE,
                tier=tier,
                expires_at=expires_at,
                hardware_mismatch=False,
                grace_ends_at=None,
                message="License expired - running in BASIC mode",
                watermark_text="LICENSE EXPIRED - BASIC MODE"
            )
        else:
            return LicenseStatus(
                state=LicenseState.LICENSED,
                tier=tier,
                expires_at=expires_at,
                hardware_mismatch=False,
                grace_ends_at=None,
                message="Licensed",
                watermark_text=None  # No watermark for licensed
            )

    def _handle_hardware_mismatch(self, tier: str, expires_at: Optional[datetime]) -> LicenseStatus:
        """Handle hardware mismatch - enter or continue grace period."""
        grace_path = Path(GRACE_FILE)

        # Check if grace period already started
        if grace_path.exists():
            try:
                with open(grace_path, 'r') as f:
                    grace_started = datetime.fromisoformat(f.read().strip())
                grace_ends = grace_started + timedelta(hours=GRACE_PERIOD_HOURS)

                if datetime.now() < grace_ends:
                    remaining = grace_ends - datetime.now()
                    hours_left = remaining.total_seconds() / 3600
                    return LicenseStatus(
                        state=LicenseState.GRACE_MODE,
                        tier=tier,
                        expires_at=expires_at,
                        hardware_mismatch=True,
                        grace_ends_at=grace_ends,
                        message=f"Hardware changed - Grace period: {hours_left:.1f}h remaining",
                        watermark_text=f"GRACE MODE - {hours_left:.0f}h LEFT"
                    )
                else:
                    # Grace period expired
                    return LicenseStatus(
                        state=LicenseState.BASIC_MODE,
                        tier=tier,
                        expires_at=expires_at,
                        hardware_mismatch=True,
                        grace_ends_at=grace_ends,
                        message="Grace period expired - running in BASIC mode",
                        watermark_text="HARDWARE MISMATCH - BASIC MODE"
                    )
            except Exception:
                pass

        # Start new grace period
        try:
            grace_path.parent.mkdir(parents=True, exist_ok=True)
            with open(grace_path, 'w') as f:
                f.write(datetime.now().isoformat())
            logger.info("Started 72-hour grace period for hardware change")
        except Exception as e:
            logger.warning(f"Failed to start grace period: {e}")

        grace_ends = datetime.now() + timedelta(hours=GRACE_PERIOD_HOURS)
        return LicenseStatus(
            state=LicenseState.GRACE_MODE,
            tier=tier,
            expires_at=expires_at,
            hardware_mismatch=True,
            grace_ends_at=grace_ends,
            message=f"Hardware changed - 72h grace period started",
            watermark_text=f"GRACE MODE - 72h LEFT"
        )

    def _create_trial_status(self) -> LicenseStatus:
        """Create trial license status."""
        return LicenseStatus(
            state=LicenseState.TRIAL,
            tier='trial',
            expires_at=None,
            hardware_mismatch=False,
            grace_ends_at=None,
            message="Trial version - no license file found",
            watermark_text="TRIAL VERSION - NOT FOR CLINICAL USE"
        )

    def set_test_mode(self, state: LicenseState) -> LicenseStatus:
        """Set license state for testing (development only)."""
        watermark_map = {
            LicenseState.LICENSED: None,
            LicenseState.GRACE_MODE: "GRACE MODE - TEST",
            LicenseState.BASIC_MODE: "BASIC MODE - TEST",
            LicenseState.TRIAL: "TRIAL VERSION - TEST"
        }

        status = LicenseStatus(
            state=state,
            tier='test',
            expires_at=None,
            hardware_mismatch=state == LicenseState.GRACE_MODE,
            grace_ends_at=datetime.now() + timedelta(hours=72) if state == LicenseState.GRACE_MODE else None,
            message=f"Test mode: {state.value}",
            watermark_text=watermark_map.get(state)
        )
        self._cache = status
        self._cache_time = time.time()
        return status


# ============================================================================
# Singleton Instance
# ============================================================================

license_manager = LicenseManager()


def get_license_status(force_refresh: bool = False) -> LicenseStatus:
    """Get current license status."""
    return license_manager.get_status(force_refresh)


def get_watermark_text() -> Optional[str]:
    """Get watermark text if needed (None if fully licensed)."""
    status = get_license_status()
    return status.watermark_text


def is_feature_allowed(feature: str) -> bool:
    """Check if a feature is allowed under current license."""
    status = get_license_status()

    # DIRECTIVE #4: DR operations are NEVER blocked
    dr_features = ['dr_restore', 'dr_export', 'lifeboat', 'basic_record']
    if feature in dr_features:
        return True

    # All features allowed for LICENSED
    if status.state == LicenseState.LICENSED:
        return True

    # GRACE_MODE: full features temporarily
    if status.state == LicenseState.GRACE_MODE:
        return True

    # TRIAL/BASIC_MODE: limited features
    basic_features = ['basic_record', 'export', 'dr_restore', 'dr_export']
    return feature in basic_features
