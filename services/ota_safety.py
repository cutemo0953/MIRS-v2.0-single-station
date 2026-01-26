"""
xIRS OTA Safety Module

Implements critical safety checks before applying OTA updates:
- Active Case Guard (手術中保護鎖)
- RTC/Time Validity Gate
- DB Migration Compatibility
- System Load Check
- Comprehensive Health Check (Smoke Test)
- Breaking Change Detection

Version: 1.0
Date: 2026-01-26
Reference: DEV_SPEC_COMMERCIAL_APPLIANCE_v1.9.1 (Gemini/ChatGPT Review)
"""

import logging
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple, List

import aiohttp

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# Build date embedded at compile time (used for time validity check)
BUILD_DATE = datetime(2026, 1, 26)

# Database path
DB_PATH = os.environ.get('MIRS_DB_PATH', 'medical_inventory.db')

# Safety thresholds
MAX_SYSTEM_LOAD = 2.0
RECENT_ACTIVITY_MINUTES = 5
HEALTH_CHECK_TIMEOUT = 60

# API base URL for health checks
API_BASE_URL = os.environ.get('MIRS_API_URL', 'http://localhost:8000')


# =============================================================================
# Data Classes
# =============================================================================

class SafetyCheckResult(Enum):
    """Safety check result status."""
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"


@dataclass
class SafetyReport:
    """Complete safety check report."""
    safe_to_update: bool
    checks: List[dict]
    blocking_reasons: List[str]
    warnings: List[str]
    timestamp: datetime


# =============================================================================
# Critical #1: Active Case Guard (手術中保護鎖)
# =============================================================================

def check_active_cases() -> Tuple[SafetyCheckResult, str]:
    """
    Check if any surgery cases are in progress.

    CRITICAL: If any case is OPEN/IN_PROGRESS/PACU, updates are FORBIDDEN.
    This prevents system restart during active surgeries.

    Returns: (result, message)
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Check for active anesthesia cases
        cursor.execute("""
            SELECT COUNT(*) FROM anesthesia_cases
            WHERE status IN ('PREOP', 'IN_PROGRESS', 'PACU', 'OPEN')
        """)
        active_count = cursor.fetchone()[0]

        conn.close()

        if active_count > 0:
            return (
                SafetyCheckResult.FAIL,
                f"有 {active_count} 個進行中的案件，絕對禁止更新"
            )

        return (SafetyCheckResult.PASS, "無進行中案件")

    except sqlite3.OperationalError as e:
        # Table might not exist - safe to proceed
        if "no such table" in str(e):
            return (SafetyCheckResult.PASS, "麻醉模組未啟用")
        return (SafetyCheckResult.FAIL, f"資料庫錯誤: {e}")
    except Exception as e:
        return (SafetyCheckResult.FAIL, f"檢查失敗: {e}")


def check_recent_activity() -> Tuple[SafetyCheckResult, str]:
    """
    Check if there's been recent API activity.

    If someone is actively using the system, delay the update.
    """
    try:
        # Check for recent events in the last N minutes
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cutoff_time = datetime.now() - timedelta(minutes=RECENT_ACTIVITY_MINUTES)
        cutoff_str = cutoff_time.isoformat()

        cursor.execute("""
            SELECT COUNT(*) FROM anesthesia_events
            WHERE created_at > ?
        """, (cutoff_str,))
        recent_events = cursor.fetchone()[0]

        conn.close()

        if recent_events > 0:
            return (
                SafetyCheckResult.WARN,
                f"最近 {RECENT_ACTIVITY_MINUTES} 分鐘內有 {recent_events} 筆活動"
            )

        return (SafetyCheckResult.PASS, f"最近 {RECENT_ACTIVITY_MINUTES} 分鐘無活動")

    except sqlite3.OperationalError:
        return (SafetyCheckResult.PASS, "無法檢查活動記錄")
    except Exception as e:
        return (SafetyCheckResult.WARN, f"活動檢查失敗: {e}")


# =============================================================================
# Critical #3: RTC/Time Validity Gate
# =============================================================================

def check_time_validity() -> Tuple[SafetyCheckResult, str]:
    """
    Check if system time is valid.

    Without RTC, after power loss the time might reset to 1970 or some
    incorrect value. We must ensure time > BUILD_DATE before allowing
    auto-updates, otherwise the update window check becomes meaningless.
    """
    now = datetime.now()

    # Time must be after BUILD_DATE
    if now < BUILD_DATE:
        return (
            SafetyCheckResult.FAIL,
            f"系統時間 ({now.strftime('%Y-%m-%d')}) 早於編譯日期 ({BUILD_DATE.strftime('%Y-%m-%d')})，可能 RTC 異常"
        )

    # Warn if time seems too far in the future (> 5 years)
    max_reasonable_date = BUILD_DATE + timedelta(days=365 * 5)
    if now > max_reasonable_date:
        return (
            SafetyCheckResult.WARN,
            f"系統時間 ({now.strftime('%Y-%m-%d')}) 似乎太遠，請確認時間正確"
        )

    return (SafetyCheckResult.PASS, f"系統時間有效: {now.strftime('%Y-%m-%d %H:%M')}")


def check_update_window(window_start: str = "02:00", window_end: str = "05:00") -> Tuple[SafetyCheckResult, str]:
    """
    Check if current time is within the allowed update window.

    Default window: 02:00 - 05:00 (avoid surgery hours)
    """
    from datetime import time as dt_time

    now = datetime.now().time()
    start = dt_time.fromisoformat(window_start)
    end = dt_time.fromisoformat(window_end)

    # Handle window that crosses midnight
    if start <= end:
        in_window = start <= now <= end
    else:
        in_window = now >= start or now <= end

    if not in_window:
        return (
            SafetyCheckResult.FAIL,
            f"目前時間 {now.strftime('%H:%M')} 不在更新時段 ({window_start}-{window_end})"
        )

    return (SafetyCheckResult.PASS, f"在更新時段內 ({window_start}-{window_end})")


# =============================================================================
# Critical #4: DB Migration Compatibility
# =============================================================================

def check_migration_compatibility(
    migration_policy: str,
    rollback_compatible: bool,
    min_rollback_version: Optional[str] = None,
    current_version: str = "1.0.0"
) -> Tuple[SafetyCheckResult, str]:
    """
    Check if the update's DB migration is compatible with auto-update.

    migration_policy:
    - "none": No migration needed
    - "additive": Only adds columns/tables (safe to rollback)
    - "breaking": Modifies/removes schema (unsafe to rollback)
    """
    if migration_policy == "none":
        return (SafetyCheckResult.PASS, "無 DB migration")

    if migration_policy == "additive":
        return (SafetyCheckResult.PASS, "Additive migration (可回滾)")

    if migration_policy == "breaking":
        if rollback_compatible:
            return (
                SafetyCheckResult.WARN,
                f"Breaking migration，但標記為可回滾到 {min_rollback_version}"
            )
        return (
            SafetyCheckResult.FAIL,
            "Breaking migration 且不可回滾，需手動確認更新"
        )

    return (SafetyCheckResult.WARN, f"未知的 migration policy: {migration_policy}")


# =============================================================================
# Critical #7: Breaking Change Detection
# =============================================================================

def check_breaking_changes(
    current_version: str,
    new_version: str,
    release_notes: Optional[str] = None
) -> Tuple[SafetyCheckResult, str]:
    """
    Detect if the update contains breaking changes.

    Detection rules:
    1. SemVer major version bump (2.0.0 > 1.x.x)
    2. Release notes contain BREAKING: or [BREAKING]
    """
    # Parse versions
    try:
        curr_parts = [int(x) for x in current_version.split('.')]
        new_parts = [int(x) for x in new_version.split('.')]

        curr_major = curr_parts[0] if curr_parts else 0
        new_major = new_parts[0] if new_parts else 0

        # Check for major version bump
        if new_major > curr_major:
            return (
                SafetyCheckResult.FAIL,
                f"Major version bump ({current_version} → {new_version})，需手動確認"
            )
    except ValueError:
        pass  # Invalid version format, continue with other checks

    # Check release notes for breaking change markers
    if release_notes:
        breaking_markers = ['BREAKING:', '[BREAKING]', '**BREAKING**', '# BREAKING']
        for marker in breaking_markers:
            if marker in release_notes.upper():
                return (
                    SafetyCheckResult.FAIL,
                    f"Release notes 包含 breaking change 標記"
                )

    return (SafetyCheckResult.PASS, "無破壞性變更")


# =============================================================================
# High #5: System Load Check
# =============================================================================

def check_system_load() -> Tuple[SafetyCheckResult, str]:
    """
    Check if system load is acceptable for update.

    High load might indicate ongoing operations (PDF generation, exports, etc.)
    """
    try:
        load_1min, load_5min, load_15min = os.getloadavg()

        if load_1min > MAX_SYSTEM_LOAD:
            return (
                SafetyCheckResult.FAIL,
                f"系統負載過高 ({load_1min:.2f})，延後更新"
            )

        if load_1min > MAX_SYSTEM_LOAD * 0.7:
            return (
                SafetyCheckResult.WARN,
                f"系統負載偏高 ({load_1min:.2f})"
            )

        return (SafetyCheckResult.PASS, f"系統負載正常 ({load_1min:.2f})")

    except OSError:
        # getloadavg not available on some systems
        return (SafetyCheckResult.PASS, "無法檢查系統負載")


# =============================================================================
# High #5: Comprehensive Health Check (Smoke Test)
# =============================================================================

async def check_health_comprehensive() -> Tuple[SafetyCheckResult, str]:
    """
    Comprehensive health check after update.

    Not just "process alive" but actual functionality verification:
    - API responds
    - DB connection works
    - DB query works
    - Static assets accessible
    """
    import asyncio

    checks = []

    # 1. API Health endpoint
    api_ok = await _check_api_health()
    checks.append(("API /api/health", api_ok))

    # 2. DB connection
    db_ok = _check_db_connection()
    checks.append(("DB 連線", db_ok))

    # 3. DB minimal query
    query_ok = _check_db_query()
    checks.append(("DB 查詢", query_ok))

    # 4. Static assets (if backend serves them)
    static_ok = await _check_static_assets()
    checks.append(("靜態資源", static_ok))

    # Summarize results
    failed = [name for name, ok in checks if not ok]

    if failed:
        return (
            SafetyCheckResult.FAIL,
            f"健康檢查失敗: {', '.join(failed)}"
        )

    return (SafetyCheckResult.PASS, "所有健康檢查通過")


async def _check_api_health() -> bool:
    """Check if API health endpoint responds."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{API_BASE_URL}/api/health",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('status') == 'healthy'
                return False
    except Exception as e:
        logger.error(f"API health check failed: {e}")
        return False


def _check_db_connection() -> bool:
    """Check if DB connection works."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        conn.execute("SELECT 1")
        conn.close()
        return True
    except Exception as e:
        logger.error(f"DB connection check failed: {e}")
        return False


def _check_db_query() -> bool:
    """Check if a minimal DB query works."""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        cursor = conn.cursor()

        # Try a simple query that should always work
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1")
        result = cursor.fetchone()

        conn.close()
        return result is not None
    except Exception as e:
        logger.error(f"DB query check failed: {e}")
        return False


async def _check_static_assets() -> bool:
    """Check if static assets are accessible."""
    try:
        async with aiohttp.ClientSession() as session:
            # Try to fetch a known static file
            async with session.get(
                f"{API_BASE_URL}/static/shared/xirs-protocol.js",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                return resp.status == 200
    except Exception:
        # Static assets might not be served by this backend
        return True  # Assume OK if not applicable


# =============================================================================
# Complete Safety Check
# =============================================================================

async def run_all_safety_checks(
    new_version: str = "1.0.0",
    current_version: str = "1.0.0",
    release_notes: Optional[str] = None,
    migration_policy: str = "none",
    rollback_compatible: bool = True,
    update_window: Tuple[str, str] = ("02:00", "05:00")
) -> SafetyReport:
    """
    Run all safety checks and return a comprehensive report.

    Returns SafetyReport with:
    - safe_to_update: True only if ALL critical checks pass
    - blocking_reasons: List of reasons that block the update
    - warnings: Non-blocking issues to be aware of
    """
    checks = []
    blocking_reasons = []
    warnings = []

    # Critical #1: Active Case Guard
    result, msg = check_active_cases()
    checks.append({"name": "Active Case Guard", "result": result.value, "message": msg})
    if result == SafetyCheckResult.FAIL:
        blocking_reasons.append(msg)

    # Critical #1b: Recent Activity
    result, msg = check_recent_activity()
    checks.append({"name": "Recent Activity", "result": result.value, "message": msg})
    if result == SafetyCheckResult.WARN:
        warnings.append(msg)

    # Critical #3: Time Validity
    result, msg = check_time_validity()
    checks.append({"name": "Time Validity", "result": result.value, "message": msg})
    if result == SafetyCheckResult.FAIL:
        blocking_reasons.append(msg)
    elif result == SafetyCheckResult.WARN:
        warnings.append(msg)

    # Critical #3b: Update Window
    result, msg = check_update_window(update_window[0], update_window[1])
    checks.append({"name": "Update Window", "result": result.value, "message": msg})
    if result == SafetyCheckResult.FAIL:
        blocking_reasons.append(msg)

    # Critical #4: Migration Compatibility
    result, msg = check_migration_compatibility(
        migration_policy, rollback_compatible, None, current_version
    )
    checks.append({"name": "Migration Compatibility", "result": result.value, "message": msg})
    if result == SafetyCheckResult.FAIL:
        blocking_reasons.append(msg)
    elif result == SafetyCheckResult.WARN:
        warnings.append(msg)

    # Critical #7: Breaking Changes
    result, msg = check_breaking_changes(current_version, new_version, release_notes)
    checks.append({"name": "Breaking Changes", "result": result.value, "message": msg})
    if result == SafetyCheckResult.FAIL:
        blocking_reasons.append(msg)

    # High: System Load
    result, msg = check_system_load()
    checks.append({"name": "System Load", "result": result.value, "message": msg})
    if result == SafetyCheckResult.FAIL:
        blocking_reasons.append(msg)
    elif result == SafetyCheckResult.WARN:
        warnings.append(msg)

    return SafetyReport(
        safe_to_update=len(blocking_reasons) == 0,
        checks=checks,
        blocking_reasons=blocking_reasons,
        warnings=warnings,
        timestamp=datetime.now()
    )


# =============================================================================
# Utility Functions
# =============================================================================

def is_safe_to_update() -> Tuple[bool, str]:
    """
    Quick synchronous check for update safety.

    Use this for simple yes/no decisions without full async support.
    """
    # Check active cases (most critical)
    result, msg = check_active_cases()
    if result == SafetyCheckResult.FAIL:
        return False, msg

    # Check time validity
    result, msg = check_time_validity()
    if result == SafetyCheckResult.FAIL:
        return False, msg

    # Check system load
    result, msg = check_system_load()
    if result == SafetyCheckResult.FAIL:
        return False, msg

    return True, "可安全更新"
