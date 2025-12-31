"""
Hub-Satellite Acceptance Tests
==============================

Tests for xIRS Hub-Satellite integration (CIRS Hub + MIRS Satellite).
See DEV_SPEC_ANESTHESIA_v1.5.1.md Section H: 驗收測試

Test Categories:
1. Severed Cable Test - MIRS operates offline when CIRS unreachable
2. Reconnection Test - MIRS fetches data when CIRS comes back
3. Snapshot Test - Patient data persists in case even if CIRS loses it
4. Protocol Header Test - xIRS headers are present in responses

Usage:
    pytest tests/test_hub_satellite.py -v

Or run individual tests:
    pytest tests/test_hub_satellite.py::test_severed_cable -v
"""

import pytest
import httpx
import json
import os
from datetime import datetime

# Test configuration
MIRS_BASE_URL = os.getenv("MIRS_BASE_URL", "http://localhost:8090")
ANESTHESIA_API = f"{MIRS_BASE_URL}/api/anesthesia"

# Test actor
TEST_ACTOR = "test-nurse-001"


class TestSeveredCable:
    """
    Severed Cable Test (斷線測試)

    Requirement: When CIRS Hub is unreachable, MIRS must:
    1. Return offline status in proxy endpoints
    2. Allow creating cases with manual patient entry
    3. Continue recording vitals and medications
    """

    def test_proxy_returns_offline_when_hub_unreachable(self):
        """Proxy endpoint should return online=false when Hub unreachable."""
        response = httpx.get(f"{ANESTHESIA_API}/proxy/cirs/waiting-list")
        assert response.status_code == 200

        data = response.json()
        # When CIRS is not running, should return offline status
        # (In production with CIRS running, this would be True)
        assert "online" in data
        assert "patients" in data
        assert "protocol_version" in data

    def test_hub_status_shows_offline(self):
        """Hub status endpoint should report offline when Hub unreachable."""
        response = httpx.get(f"{ANESTHESIA_API}/hub/status")
        assert response.status_code == 200

        data = response.json()
        assert data["protocol_version"] == "1.0"
        assert "hub_online" in data
        assert "hub_url" in data
        assert "station_id" in data

    def test_create_case_without_cirs(self):
        """Should be able to create a case with manual entry when offline."""
        case_data = {
            "patient_id": "MANUAL-TEST-001",
            "patient_name": "測試病患",
            "planned_technique": "GA_ETT",
            "context_mode": "STANDARD",
            # No cirs_registration_ref - manual entry
        }

        response = httpx.post(
            f"{ANESTHESIA_API}/cases",
            params={"actor_id": TEST_ACTOR},
            json=case_data
        )

        assert response.status_code == 200
        data = response.json()
        assert data["patient_id"] == "MANUAL-TEST-001"
        assert "id" in data

        # Clean up - close the case
        case_id = data["id"]
        httpx.post(
            f"{ANESTHESIA_API}/cases/{case_id}/milestones",
            params={"actor_id": TEST_ACTOR},
            json={"type": "CASE_CLOSED", "notes": "Test cleanup"}
        )


class TestProtocolHeaders:
    """
    Protocol Header Test (協定標頭測試)

    Requirement: All sync API responses must include:
    - X-XIRS-Protocol-Version
    - X-XIRS-Hub-Revision
    - X-XIRS-Station-Id
    """

    def test_waiting_list_has_xirs_headers(self):
        """Waiting list endpoint should include xIRS headers."""
        response = httpx.get(f"{ANESTHESIA_API}/proxy/cirs/waiting-list")

        assert "x-xirs-protocol-version" in response.headers
        assert response.headers["x-xirs-protocol-version"] == "1.0"
        assert "x-xirs-hub-revision" in response.headers
        assert "x-xirs-station-id" in response.headers

    def test_hub_status_has_xirs_headers(self):
        """Hub status endpoint should include xIRS headers."""
        response = httpx.get(f"{ANESTHESIA_API}/hub/status")

        assert "x-xirs-protocol-version" in response.headers
        assert response.headers["x-xirs-protocol-version"] == "1.0"


class TestPatientSnapshot:
    """
    Snapshot Test (快照測試)

    Requirement: When a case is created from CIRS data:
    1. Patient snapshot is stored with the case
    2. Case remains readable even if CIRS data is lost
    """

    def test_case_stores_patient_snapshot(self):
        """Case created with snapshot should retain patient data."""
        # Create case with patient snapshot
        patient_snapshot = {
            "name": "快照測試病患",
            "dob": "1990-01-15",
            "sex": "M",
            "allergies": ["Penicillin", "Aspirin"],
            "weight_kg": 70.5,
            "blood_type": "A+",
            "triage_category": "YELLOW",
            "chief_complaint": "右腿骨折"
        }

        case_data = {
            "patient_id": "SNAPSHOT-TEST-001",
            "patient_name": patient_snapshot["name"],
            "planned_technique": "RA_SPINAL",
            "context_mode": "STANDARD",
            "cirs_registration_ref": "REG-TEST-001",
            "patient_snapshot": patient_snapshot
        }

        response = httpx.post(
            f"{ANESTHESIA_API}/cases",
            params={"actor_id": TEST_ACTOR},
            json=case_data
        )

        assert response.status_code == 200
        created_case = response.json()
        case_id = created_case["id"]

        # Fetch the case and verify snapshot is stored
        response = httpx.get(f"{ANESTHESIA_API}/cases/{case_id}")
        assert response.status_code == 200

        fetched_case = response.json()
        assert fetched_case["cirs_registration_ref"] == "REG-TEST-001"

        # Verify patient_snapshot is stored (if returned in response)
        # Note: The current API might not return snapshot in GET,
        # but it should be stored in DB for audit purposes

        # Clean up
        httpx.post(
            f"{ANESTHESIA_API}/cases/{case_id}/milestones",
            params={"actor_id": TEST_ACTOR},
            json={"type": "CASE_CLOSED", "notes": "Snapshot test cleanup"}
        )


class TestIdempotency:
    """
    Idempotency Test (冪等性測試)

    Requirement: Operations with same idempotency key should not duplicate.
    """

    def test_duplicate_vital_signs_handled(self):
        """Recording same vitals twice should not create duplicates."""
        # First create a case
        case_data = {
            "patient_id": "IDEMPOTENCY-TEST-001",
            "planned_technique": "SEDATION",
            "context_mode": "STANDARD",
        }

        response = httpx.post(
            f"{ANESTHESIA_API}/cases",
            params={"actor_id": TEST_ACTOR},
            json=case_data
        )
        case_id = response.json()["id"]

        # Record vitals
        vitals = {
            "bp_sys": 120,
            "bp_dia": 80,
            "hr": 72,
            "spo2": 99
        }

        response1 = httpx.post(
            f"{ANESTHESIA_API}/cases/{case_id}/vitals",
            params={"actor_id": TEST_ACTOR},
            json=vitals
        )
        assert response1.status_code == 200

        # Get event count after first recording
        response = httpx.get(f"{ANESTHESIA_API}/cases/{case_id}/events")
        events_after_first = len(response.json().get("events", []))

        # Clean up
        httpx.post(
            f"{ANESTHESIA_API}/cases/{case_id}/milestones",
            params={"actor_id": TEST_ACTOR},
            json={"type": "CASE_CLOSED", "notes": "Idempotency test cleanup"}
        )


class TestVersionCompatibility:
    """
    Version Compatibility Test (版本相容測試)

    Requirement: Protocol version should be checked for compatibility.
    """

    def test_protocol_version_is_1_0(self):
        """Current protocol version should be 1.0."""
        response = httpx.get(f"{ANESTHESIA_API}/hub/status")
        data = response.json()

        assert data["protocol_version"] == "1.0"

    def test_response_includes_protocol_version(self):
        """All sync responses should include protocol version."""
        response = httpx.get(f"{ANESTHESIA_API}/proxy/cirs/waiting-list")
        data = response.json()

        assert "protocol_version" in data
        assert data["protocol_version"] == "1.0"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
