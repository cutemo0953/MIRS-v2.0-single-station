"""
MIRS Procedure Module - CIRS Integration
v1.0 - 處置流程 CIRS 整合
v1.2 - 加入 timestamp 支援離線判斷

提供:
1. CIRS 待處置清單 proxy 端點
2. 處置完成通知 CIRS
"""

import os
import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/procedure", tags=["procedure"])


# =============================================================================
# Configuration
# =============================================================================

CIRS_HUB_URL = os.getenv("CIRS_HUB_URL", "http://localhost:8090")
CIRS_TIMEOUT = 5.0  # seconds
XIRS_PROTOCOL_VERSION = "1.1"

# Try to import httpx (optional dependency)
try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    logger.warning("httpx not available - CIRS integration disabled")


# =============================================================================
# Helper Functions
# =============================================================================

def get_station_id():
    """Get current station ID from config or environment"""
    return os.getenv("STATION_ID", "MIRS-001")


def make_xirs_response(data: dict, hub_revision: int = 0):
    """Create response with xIRS protocol headers"""
    response = JSONResponse(content=data)
    response.headers["X-XIRS-Protocol-Version"] = XIRS_PROTOCOL_VERSION
    response.headers["X-XIRS-Hub-Revision"] = str(hub_revision)
    response.headers["X-XIRS-Station-Id"] = get_station_id()
    return response


# =============================================================================
# CIRS Proxy Endpoints
# =============================================================================

@router.get("/proxy/cirs/waiting-procedure")
async def get_cirs_waiting_procedure():
    """
    v1.1: 取得待處置清單 (使用 CIRS /waiting/procedure 端點)

    只返回:
    - status = CONSULTATION_DONE
    - needs_procedure = 1

    這是 v1.1 流程改進的核心：醫師完成看診後勾選「需處置」的病患才會出現。
    """
    if not HTTPX_AVAILABLE:
        return make_xirs_response({
            "online": False,
            "source": "offline",
            "queue": "PROCEDURE",
            "patients": [],
            "count": 0,
            "error": "httpx not installed",
            "protocol_version": XIRS_PROTOCOL_VERSION
        })

    hub_revision = 0

    try:
        async with httpx.AsyncClient(timeout=CIRS_TIMEOUT) as client:
            response = await client.get(
                f"{CIRS_HUB_URL}/api/registrations/waiting/procedure"
            )

            hub_revision = int(response.headers.get("X-XIRS-Hub-Revision", 0))

            if response.status_code == 200:
                data = response.json()
                # Transform CIRS data to MIRS format
                patients = []
                for reg in data.get("items", []):
                    patients.append({
                        "registration_id": reg.get("reg_id"),
                        "patient_id": reg.get("person_id"),
                        "patient_ref": reg.get("patient_ref"),
                        "name": reg.get("display_name"),
                        "age_group": reg.get("age_group"),
                        "sex": reg.get("gender"),
                        "triage_category": reg.get("triage"),
                        "priority": reg.get("priority"),
                        "chief_complaint": reg.get("chief_complaint"),
                        "procedure_notes": reg.get("procedure_notes"),
                        "consultation_by": reg.get("consultation_by"),
                        "consultation_completed_at": reg.get("consultation_completed_at"),
                        "waiting_minutes": reg.get("waiting_minutes"),
                        "claimed_by": reg.get("procedure_claimed_by"),
                        "claimed_at": reg.get("procedure_claimed_at")
                    })

                # v1.2: 加入 timestamp 支援離線判斷
                local_timestamp = datetime.now().isoformat()
                hub_timestamp = response.headers.get("Date", local_timestamp)

                return make_xirs_response({
                    "online": True,
                    "source": "cirs_hub",
                    "queue": "PROCEDURE",
                    "patients": patients,
                    "count": len(patients),
                    "protocol_version": XIRS_PROTOCOL_VERSION,
                    "hub_timestamp": hub_timestamp,
                    "local_timestamp": local_timestamp
                }, hub_revision)
            else:
                logger.warning(f"CIRS Hub waiting/procedure returned {response.status_code}")
                return make_xirs_response({
                    "online": False,
                    "source": "offline",
                    "queue": "PROCEDURE",
                    "patients": [],
                    "count": 0,
                    "error": f"CIRS returned status {response.status_code}",
                    "protocol_version": XIRS_PROTOCOL_VERSION,
                    "local_timestamp": datetime.now().isoformat()
                }, hub_revision)

    except httpx.TimeoutException:
        logger.warning("CIRS Hub timeout for waiting/procedure")
        return make_xirs_response({
            "online": False,
            "source": "offline",
            "queue": "PROCEDURE",
            "patients": [],
            "count": 0,
            "error": "CIRS Hub timeout",
            "protocol_version": XIRS_PROTOCOL_VERSION,
            "local_timestamp": datetime.now().isoformat()
        })
    except httpx.ConnectError:
        logger.info("CIRS Hub not reachable for waiting/procedure")
        return make_xirs_response({
            "online": False,
            "source": "offline",
            "queue": "PROCEDURE",
            "patients": [],
            "count": 0,
            "error": "CIRS Hub not reachable",
            "protocol_version": XIRS_PROTOCOL_VERSION,
            "local_timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"CIRS waiting/procedure proxy error: {e}")
        return make_xirs_response({
            "online": False,
            "source": "offline",
            "queue": "PROCEDURE",
            "patients": [],
            "count": 0,
            "error": str(e),
            "protocol_version": XIRS_PROTOCOL_VERSION,
            "local_timestamp": datetime.now().isoformat()
        })


# =============================================================================
# CIRS Notification Functions
# =============================================================================

async def notify_cirs_procedure_claim(registration_id: str, actor_id: str) -> bool:
    """
    Notify CIRS Hub that a procedure station has claimed this patient.

    Args:
        registration_id: CIRS registration ID (REG-xxx)
        actor_id: ID of the procedure station/operator

    Returns:
        True if notification successful, False otherwise
    """
    if not HTTPX_AVAILABLE:
        logger.warning("Cannot notify CIRS - httpx not available")
        return False

    try:
        async with httpx.AsyncClient(timeout=CIRS_TIMEOUT) as client:
            response = await client.post(
                f"{CIRS_HUB_URL}/api/registrations/{registration_id}/role-claim",
                json={"role": "PROCEDURE", "actor_id": actor_id}
            )

            if response.status_code == 200:
                logger.info(f"Successfully claimed registration {registration_id} for PROCEDURE")
                return True
            else:
                logger.warning(f"Failed to claim registration: {response.status_code}")
                return False

    except Exception as e:
        logger.warning(f"Failed to notify CIRS of procedure claim: {e}")
        return False


async def notify_cirs_procedure_done(
    registration_id: str,
    procedure_record_id: str,
    actor_id: str
) -> bool:
    """
    Notify CIRS Hub that procedure is complete.

    This will:
    1. Set needs_procedure = 0
    2. Release the PROCEDURE claim
    3. If needs_anesthesia is also 0, set status = COMPLETED

    Args:
        registration_id: CIRS registration ID (REG-xxx)
        procedure_record_id: MIRS procedure record ID
        actor_id: ID of the procedure station/operator

    Returns:
        True if notification successful, False otherwise
    """
    if not HTTPX_AVAILABLE:
        logger.warning("Cannot notify CIRS - httpx not available")
        return False

    try:
        async with httpx.AsyncClient(timeout=CIRS_TIMEOUT) as client:
            response = await client.post(
                f"{CIRS_HUB_URL}/api/registrations/{registration_id}/procedure-done",
                json={
                    "procedure_record_id": procedure_record_id,
                    "actor_id": actor_id
                }
            )

            if response.status_code == 200:
                logger.info(f"Successfully notified CIRS procedure done for {registration_id}")
                return True
            else:
                logger.warning(f"Failed to notify procedure done: {response.status_code}")
                return False

    except Exception as e:
        logger.warning(f"Failed to notify CIRS of procedure completion: {e}")
        return False
