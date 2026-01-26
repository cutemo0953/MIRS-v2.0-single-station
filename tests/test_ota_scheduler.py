"""
OTA Scheduler Automated Tests

Tests for P3-02a OTA Auto-Update Scheduler safety features.

Usage:
    # Run all tests
    python -m pytest tests/test_ota_scheduler.py -v

    # Run specific test
    python -m pytest tests/test_ota_scheduler.py::test_active_case_guard -v

    # Run without pytest (standalone)
    python tests/test_ota_scheduler.py

Version: 1.0
Date: 2026-01-26
"""

import asyncio
import os
import sys
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


# =============================================================================
# Test Fixtures
# =============================================================================

def create_test_db(with_active_case: bool = False) -> str:
    """Create a temporary test database."""
    fd, db_path = tempfile.mkstemp(suffix='.db')
    os.close(fd)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Create anesthesia_cases table
    cursor.execute("""
        CREATE TABLE anesthesia_cases (
            id TEXT PRIMARY KEY,
            status TEXT,
            created_at TEXT
        )
    """)

    # Create anesthesia_events table
    cursor.execute("""
        CREATE TABLE anesthesia_events (
            id TEXT PRIMARY KEY,
            case_id TEXT,
            event_type TEXT,
            created_at TEXT
        )
    """)

    if with_active_case:
        cursor.execute("""
            INSERT INTO anesthesia_cases (id, status, created_at)
            VALUES ('TEST-001', 'IN_PROGRESS', ?)
        """, (datetime.now().isoformat(),))

    conn.commit()
    conn.close()

    return db_path


# =============================================================================
# Test: Active Case Guard (Critical #1)
# =============================================================================

def test_active_case_guard_blocks_when_surgery_active():
    """Test that updates are blocked when surgery is in progress."""
    db_path = create_test_db(with_active_case=True)

    try:
        with patch('services.ota_safety.DB_PATH', db_path):
            from services.ota_safety import check_active_cases, SafetyCheckResult

            result, msg = check_active_cases()

            assert result == SafetyCheckResult.FAIL, f"Expected FAIL, got {result}"
            assert "1" in msg, f"Should mention 1 active case: {msg}"
            print(f"✅ Active case guard: BLOCKED - {msg}")
    finally:
        os.unlink(db_path)


def test_active_case_guard_allows_when_no_surgery():
    """Test that updates are allowed when no surgery is active."""
    db_path = create_test_db(with_active_case=False)

    try:
        with patch('services.ota_safety.DB_PATH', db_path):
            from services.ota_safety import check_active_cases, SafetyCheckResult

            result, msg = check_active_cases()

            assert result == SafetyCheckResult.PASS, f"Expected PASS, got {result}"
            print(f"✅ Active case guard: ALLOWED - {msg}")
    finally:
        os.unlink(db_path)


# =============================================================================
# Test: Time Validity Gate (Critical #3)
# =============================================================================

def test_time_validity_blocks_invalid_time():
    """Test that updates are blocked if system time is before BUILD_DATE."""
    from services.ota_safety import check_time_validity, SafetyCheckResult, BUILD_DATE

    # Mock datetime to return a date before BUILD_DATE
    fake_past = BUILD_DATE - timedelta(days=365)

    with patch('services.ota_safety.datetime') as mock_dt:
        mock_dt.now.return_value = fake_past
        mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)

        result, msg = check_time_validity()

        assert result == SafetyCheckResult.FAIL, f"Expected FAIL for past date, got {result}"
        print(f"✅ Time validity (past date): BLOCKED - {msg}")


def test_time_validity_allows_valid_time():
    """Test that updates are allowed if system time is valid."""
    from services.ota_safety import check_time_validity, SafetyCheckResult

    result, msg = check_time_validity()

    # Current time should be valid (after BUILD_DATE)
    assert result in [SafetyCheckResult.PASS, SafetyCheckResult.WARN], f"Expected PASS/WARN, got {result}"
    print(f"✅ Time validity (current): {result.value} - {msg}")


# =============================================================================
# Test: Update Window (Critical #3b)
# =============================================================================

def test_update_window_blocks_outside_window():
    """Test that updates are blocked outside the update window."""
    from services.ota_safety import check_update_window, SafetyCheckResult

    # Test with window 02:00-05:00, mock time to 12:00
    with patch('services.ota_safety.datetime') as mock_dt:
        mock_dt.now.return_value.time.return_value = datetime.strptime("12:00", "%H:%M").time()

        result, msg = check_update_window("02:00", "05:00")

        assert result == SafetyCheckResult.FAIL, f"Expected FAIL outside window, got {result}"
        print(f"✅ Update window (outside): BLOCKED - {msg}")


def test_update_window_allows_inside_window():
    """Test that updates are allowed inside the update window."""
    from services.ota_safety import check_update_window, SafetyCheckResult

    # Test with window 02:00-05:00, mock time to 03:00
    with patch('services.ota_safety.datetime') as mock_dt:
        mock_dt.now.return_value.time.return_value = datetime.strptime("03:00", "%H:%M").time()

        result, msg = check_update_window("02:00", "05:00")

        assert result == SafetyCheckResult.PASS, f"Expected PASS inside window, got {result}"
        print(f"✅ Update window (inside): ALLOWED - {msg}")


# =============================================================================
# Test: Breaking Change Detection (Critical #7)
# =============================================================================

def test_breaking_change_blocks_major_version():
    """Test that major version bumps are blocked."""
    from services.ota_safety import check_breaking_changes, SafetyCheckResult

    result, msg = check_breaking_changes(
        current_version="1.5.0",
        new_version="2.0.0"
    )

    assert result == SafetyCheckResult.FAIL, f"Expected FAIL for major bump, got {result}"
    print(f"✅ Breaking change (major version): BLOCKED - {msg}")


def test_breaking_change_allows_minor_version():
    """Test that minor version bumps are allowed."""
    from services.ota_safety import check_breaking_changes, SafetyCheckResult

    result, msg = check_breaking_changes(
        current_version="1.5.0",
        new_version="1.6.0"
    )

    assert result == SafetyCheckResult.PASS, f"Expected PASS for minor bump, got {result}"
    print(f"✅ Breaking change (minor version): ALLOWED - {msg}")


def test_breaking_change_blocks_breaking_marker():
    """Test that BREAKING marker in release notes is blocked."""
    from services.ota_safety import check_breaking_changes, SafetyCheckResult

    result, msg = check_breaking_changes(
        current_version="1.5.0",
        new_version="1.5.1",
        release_notes="Fix bug. BREAKING: API changed."
    )

    assert result == SafetyCheckResult.FAIL, f"Expected FAIL for BREAKING marker, got {result}"
    print(f"✅ Breaking change (BREAKING marker): BLOCKED - {msg}")


# =============================================================================
# Test: Migration Compatibility (Critical #4)
# =============================================================================

def test_migration_blocks_breaking_non_rollback():
    """Test that breaking migrations without rollback are blocked."""
    from services.ota_safety import check_migration_compatibility, SafetyCheckResult

    result, msg = check_migration_compatibility(
        migration_policy="breaking",
        rollback_compatible=False
    )

    assert result == SafetyCheckResult.FAIL, f"Expected FAIL for non-rollback breaking, got {result}"
    print(f"✅ Migration (breaking, no rollback): BLOCKED - {msg}")


def test_migration_allows_additive():
    """Test that additive migrations are allowed."""
    from services.ota_safety import check_migration_compatibility, SafetyCheckResult

    result, msg = check_migration_compatibility(
        migration_policy="additive",
        rollback_compatible=True
    )

    assert result == SafetyCheckResult.PASS, f"Expected PASS for additive, got {result}"
    print(f"✅ Migration (additive): ALLOWED - {msg}")


# =============================================================================
# Test: System Load (High #5)
# =============================================================================

def test_system_load_blocks_high_load():
    """Test that high system load blocks updates."""
    from services.ota_safety import check_system_load, SafetyCheckResult, MAX_SYSTEM_LOAD

    # Mock high load
    with patch('os.getloadavg', return_value=(MAX_SYSTEM_LOAD + 1, 1.0, 1.0)):
        result, msg = check_system_load()

        assert result == SafetyCheckResult.FAIL, f"Expected FAIL for high load, got {result}"
        print(f"✅ System load (high): BLOCKED - {msg}")


def test_system_load_allows_normal_load():
    """Test that normal system load allows updates."""
    from services.ota_safety import check_system_load, SafetyCheckResult

    # Mock normal load
    with patch('os.getloadavg', return_value=(0.5, 0.5, 0.5)):
        result, msg = check_system_load()

        assert result == SafetyCheckResult.PASS, f"Expected PASS for normal load, got {result}"
        print(f"✅ System load (normal): ALLOWED - {msg}")


# =============================================================================
# Test: Signature Verification (Critical #2)
# =============================================================================

def test_signature_checksum_valid():
    """Test that valid checksums pass verification."""
    import hashlib

    # Create a temp file
    fd, file_path = tempfile.mkstemp()
    os.write(fd, b"test content")
    os.close(fd)

    try:
        from services.ota_security import verify_checksum

        # Calculate actual checksum
        expected = hashlib.sha256(b"test content").hexdigest()

        result = verify_checksum(file_path, expected)

        assert result.valid, f"Expected valid checksum: {result.message}"
        print(f"✅ Checksum verification: VALID - {result.message}")
    finally:
        os.unlink(file_path)


def test_signature_checksum_invalid():
    """Test that invalid checksums fail verification."""
    fd, file_path = tempfile.mkstemp()
    os.write(fd, b"test content")
    os.close(fd)

    try:
        from services.ota_security import verify_checksum

        result = verify_checksum(file_path, "invalid_checksum_here")

        assert not result.valid, f"Expected invalid checksum: {result.message}"
        print(f"✅ Checksum verification: INVALID (as expected) - {result.message}")
    finally:
        os.unlink(file_path)


# =============================================================================
# Test: Scheduler Status
# =============================================================================

def test_scheduler_status():
    """Test scheduler status endpoint."""
    from services.ota_scheduler import OTAScheduler

    scheduler = OTAScheduler()
    status = scheduler.get_status()

    assert "running" in status
    assert "auto_update_enabled" in status
    assert "check_interval_seconds" in status
    assert "update_window" in status

    print(f"✅ Scheduler status: {status}")


# =============================================================================
# Test: is_safe_to_update (Quick Check)
# =============================================================================

def test_is_safe_to_update_quick_check():
    """Test quick safety check function."""
    db_path = create_test_db(with_active_case=False)

    try:
        with patch('services.ota_safety.DB_PATH', db_path):
            from services.ota_safety import is_safe_to_update

            safe, reason = is_safe_to_update()

            print(f"✅ Quick safety check: safe={safe}, reason={reason}")
    finally:
        os.unlink(db_path)


# =============================================================================
# Test Runner
# =============================================================================

def run_all_tests():
    """Run all tests without pytest."""
    print("\n" + "=" * 60)
    print("OTA Scheduler Automated Tests")
    print("=" * 60 + "\n")

    tests = [
        # Critical #1: Active Case Guard
        ("Active Case Guard - Blocks", test_active_case_guard_blocks_when_surgery_active),
        ("Active Case Guard - Allows", test_active_case_guard_allows_when_no_surgery),

        # Critical #3: Time Validity
        ("Time Validity - Valid", test_time_validity_allows_valid_time),

        # Critical #7: Breaking Changes
        ("Breaking Change - Major Version", test_breaking_change_blocks_major_version),
        ("Breaking Change - Minor Version", test_breaking_change_allows_minor_version),
        ("Breaking Change - BREAKING Marker", test_breaking_change_blocks_breaking_marker),

        # Critical #4: Migration
        ("Migration - Breaking No Rollback", test_migration_blocks_breaking_non_rollback),
        ("Migration - Additive", test_migration_allows_additive),

        # High #5: System Load
        ("System Load - High", test_system_load_blocks_high_load),
        ("System Load - Normal", test_system_load_allows_normal_load),

        # Critical #2: Signature
        ("Checksum - Valid", test_signature_checksum_valid),
        ("Checksum - Invalid", test_signature_checksum_invalid),

        # Scheduler
        ("Scheduler Status", test_scheduler_status),

        # Quick Check
        ("Quick Safety Check", test_is_safe_to_update_quick_check),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            print(f"\n--- {name} ---")
            test_func()
            passed += 1
        except Exception as e:
            print(f"❌ {name}: FAILED - {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60 + "\n")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
