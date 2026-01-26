#!/usr/bin/env python3
"""
MIRS Unified Test Harness (P3-05)

Integrates all test modules into a single runner with JSON report output.

Usage:
    # Run all tests
    python tests/run_all_tests.py

    # Run specific test suite
    python tests/run_all_tests.py --suite ota
    python tests/run_all_tests.py --suite hub
    python tests/run_all_tests.py --suite crypto

    # Output JSON report
    python tests/run_all_tests.py --json

    # Run on RPi with API tests
    python tests/run_all_tests.py --api-tests

Version: 1.0
Date: 2026-01-26
Reference: P3-05 Automated Test Harness
"""

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# =============================================================================
# Test Result Classes
# =============================================================================

class TestResult:
    """Individual test result."""
    def __init__(self, name: str, passed: bool, message: str = "", duration: float = 0):
        self.name = name
        self.passed = passed
        self.message = message
        self.duration = duration

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "message": self.message,
            "duration_ms": round(self.duration * 1000, 2)
        }


class TestSuite:
    """Collection of test results."""
    def __init__(self, name: str):
        self.name = name
        self.results: List[TestResult] = []
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None

    def add_result(self, result: TestResult):
        self.results.append(result)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def duration(self) -> float:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return sum(r.duration for r in self.results)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "failed": self.failed,
            "total": self.total,
            "duration_seconds": round(self.duration, 2),
            "results": [r.to_dict() for r in self.results]
        }


# =============================================================================
# Test Runners
# =============================================================================

def run_ota_tests() -> TestSuite:
    """Run OTA Scheduler tests."""
    suite = TestSuite("OTA Scheduler")
    suite.start_time = datetime.now()

    try:
        from tests.test_ota_scheduler import (
            test_active_case_guard_blocks_when_surgery_active,
            test_active_case_guard_allows_when_no_surgery,
            test_time_validity_allows_valid_time,
            test_breaking_change_blocks_major_version,
            test_breaking_change_allows_minor_version,
            test_breaking_change_blocks_breaking_marker,
            test_migration_blocks_breaking_non_rollback,
            test_migration_allows_additive,
            test_system_load_blocks_high_load,
            test_system_load_allows_normal_load,
            test_signature_checksum_valid,
            test_signature_checksum_invalid,
            test_scheduler_status,
            test_is_safe_to_update_quick_check,
        )

        tests = [
            ("Active Case Guard - Blocks", test_active_case_guard_blocks_when_surgery_active),
            ("Active Case Guard - Allows", test_active_case_guard_allows_when_no_surgery),
            ("Time Validity", test_time_validity_allows_valid_time),
            ("Breaking Change - Major", test_breaking_change_blocks_major_version),
            ("Breaking Change - Minor", test_breaking_change_allows_minor_version),
            ("Breaking Change - Marker", test_breaking_change_blocks_breaking_marker),
            ("Migration - Breaking", test_migration_blocks_breaking_non_rollback),
            ("Migration - Additive", test_migration_allows_additive),
            ("System Load - High", test_system_load_blocks_high_load),
            ("System Load - Normal", test_system_load_allows_normal_load),
            ("Checksum - Valid", test_signature_checksum_valid),
            ("Checksum - Invalid", test_signature_checksum_invalid),
            ("Scheduler Status", test_scheduler_status),
            ("Quick Safety Check", test_is_safe_to_update_quick_check),
        ]

        for name, test_func in tests:
            start = time.time()
            try:
                test_func()
                suite.add_result(TestResult(name, True, "OK", time.time() - start))
            except Exception as e:
                suite.add_result(TestResult(name, False, str(e), time.time() - start))

    except ImportError as e:
        suite.add_result(TestResult("Import", False, f"Failed to import OTA tests: {e}"))

    suite.end_time = datetime.now()
    return suite


def run_hub_satellite_tests() -> TestSuite:
    """Run Hub-Satellite tests."""
    suite = TestSuite("Hub-Satellite")
    suite.start_time = datetime.now()

    try:
        # Check if test file exists
        test_file = Path(__file__).parent / "test_hub_satellite.py"
        if not test_file.exists():
            suite.add_result(TestResult("File Check", False, "test_hub_satellite.py not found"))
            suite.end_time = datetime.now()
            return suite

        # Try to import test functions
        test_hub_discovery = None
        test_satellite_registration = None

        try:
            from tests.test_hub_satellite import test_hub_discovery, test_satellite_registration
        except ImportError:
            pass

        if test_hub_discovery:
            tests = [
                ("Hub Discovery", test_hub_discovery),
                ("Satellite Registration", test_satellite_registration),
            ]

            for name, test_func in tests:
                start = time.time()
                try:
                    test_func()
                    suite.add_result(TestResult(name, True, "OK", time.time() - start))
                except Exception as e:
                    suite.add_result(TestResult(name, False, str(e), time.time() - start))
        else:
            suite.add_result(TestResult("Import", False, "Hub-Satellite tests not found"))

    except ImportError as e:
        suite.add_result(TestResult("Import", False, f"Failed to import Hub-Satellite tests: {e}"))
    except Exception as e:
        suite.add_result(TestResult("Runtime", False, f"Error: {e}"))

    suite.end_time = datetime.now()
    return suite


def run_crypto_tests() -> TestSuite:
    """Run cryptography tests."""
    suite = TestSuite("Cryptography")
    suite.start_time = datetime.now()

    try:
        # Check if test file exists
        test_file = Path(__file__).parent.parent / "services" / "security" / "test_crypto.py"
        if not test_file.exists():
            suite.add_result(TestResult("File Check", False, "test_crypto.py not found"))
            suite.end_time = datetime.now()
            return suite

        # Import and run
        sys.path.insert(0, str(test_file.parent))
        import test_crypto

        if hasattr(test_crypto, 'run_tests'):
            start = time.time()
            try:
                results = test_crypto.run_tests()
                suite.add_result(TestResult("Crypto Suite", True, "All tests passed", time.time() - start))
            except Exception as e:
                suite.add_result(TestResult("Crypto Suite", False, str(e), time.time() - start))
        else:
            suite.add_result(TestResult("Import", False, "run_tests() not found in test_crypto.py"))

    except ImportError as e:
        suite.add_result(TestResult("Import", False, f"Failed to import crypto tests: {e}"))
    except Exception as e:
        suite.add_result(TestResult("Runtime", False, f"Error: {e}"))

    suite.end_time = datetime.now()
    return suite


def run_api_tests(base_url: str = "http://localhost:8000") -> TestSuite:
    """Run API endpoint tests (requires running server)."""
    import urllib.request
    import urllib.error

    suite = TestSuite("API Endpoints")
    suite.start_time = datetime.now()

    endpoints = [
        ("/api/health", "Health Check"),
        ("/api/ota/status", "OTA Status"),
        ("/api/ota/safety/check", "OTA Safety Check"),
        ("/api/ota/scheduler/status", "OTA Scheduler Status"),
        ("/api/equipment", "Equipment List"),
        ("/api/blood/inventory", "Blood Inventory"),
    ]

    for endpoint, name in endpoints:
        start = time.time()
        try:
            url = f"{base_url}{endpoint}"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as response:
                data = response.read()
                if response.status == 200:
                    suite.add_result(TestResult(name, True, f"HTTP 200", time.time() - start))
                else:
                    suite.add_result(TestResult(name, False, f"HTTP {response.status}", time.time() - start))
        except urllib.error.HTTPError as e:
            suite.add_result(TestResult(name, False, f"HTTP {e.code}", time.time() - start))
        except urllib.error.URLError as e:
            suite.add_result(TestResult(name, False, f"Connection error: {e.reason}", time.time() - start))
        except Exception as e:
            suite.add_result(TestResult(name, False, str(e), time.time() - start))

    suite.end_time = datetime.now()
    return suite


# =============================================================================
# Main Runner
# =============================================================================

def run_all_tests(
    suites: Optional[List[str]] = None,
    api_tests: bool = False,
    base_url: str = "http://localhost:8000"
) -> Dict:
    """Run all test suites and return results."""
    all_suites: List[TestSuite] = []

    available_suites = {
        "ota": run_ota_tests,
        "hub": run_hub_satellite_tests,
        "crypto": run_crypto_tests,
    }

    # Determine which suites to run
    if suites:
        to_run = {k: v for k, v in available_suites.items() if k in suites}
    else:
        to_run = available_suites

    # Run selected suites
    for name, runner in to_run.items():
        print(f"\n{'='*60}")
        print(f"Running: {name.upper()} Tests")
        print('='*60)
        suite = runner()
        all_suites.append(suite)

        # Print results
        for result in suite.results:
            status = "✅" if result.passed else "❌"
            print(f"  {status} {result.name}: {result.message}")

        print(f"\n  Summary: {suite.passed}/{suite.total} passed")

    # Run API tests if requested
    if api_tests:
        print(f"\n{'='*60}")
        print("Running: API Tests")
        print('='*60)
        suite = run_api_tests(base_url)
        all_suites.append(suite)

        for result in suite.results:
            status = "✅" if result.passed else "❌"
            print(f"  {status} {result.name}: {result.message}")

        print(f"\n  Summary: {suite.passed}/{suite.total} passed")

    # Calculate totals
    total_passed = sum(s.passed for s in all_suites)
    total_failed = sum(s.failed for s in all_suites)
    total_tests = sum(s.total for s in all_suites)
    total_duration = sum(s.duration for s in all_suites)

    return {
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "total": total_tests,
            "passed": total_passed,
            "failed": total_failed,
            "duration_seconds": round(total_duration, 2),
            "success_rate": round(total_passed / total_tests * 100, 1) if total_tests > 0 else 0
        },
        "suites": [s.to_dict() for s in all_suites]
    }


def main():
    parser = argparse.ArgumentParser(description="MIRS Unified Test Harness")
    parser.add_argument("--suite", "-s", choices=["ota", "hub", "crypto"], action="append",
                        help="Run specific test suite(s)")
    parser.add_argument("--api-tests", "-a", action="store_true",
                        help="Include API endpoint tests (requires running server)")
    parser.add_argument("--base-url", "-u", default="http://localhost:8000",
                        help="Base URL for API tests")
    parser.add_argument("--json", "-j", action="store_true",
                        help="Output results as JSON")
    parser.add_argument("--output", "-o", type=str,
                        help="Write JSON report to file")

    args = parser.parse_args()

    print("\n" + "="*60)
    print("MIRS Unified Test Harness")
    print("="*60)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    results = run_all_tests(
        suites=args.suite,
        api_tests=args.api_tests,
        base_url=args.base_url
    )

    # Print summary
    print("\n" + "="*60)
    print("FINAL SUMMARY")
    print("="*60)
    s = results["summary"]
    print(f"Total: {s['total']} tests")
    print(f"Passed: {s['passed']} ({s['success_rate']}%)")
    print(f"Failed: {s['failed']}")
    print(f"Duration: {s['duration_seconds']}s")
    print("="*60 + "\n")

    # Output JSON
    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"Report saved to: {args.output}")

    # Exit with appropriate code
    sys.exit(0 if s['failed'] == 0 else 1)


if __name__ == "__main__":
    main()
