"""
xIRS OTA Update API Routes

Provides REST endpoints for OTA update management.

Version: 1.1
Date: 2026-01-26
Reference: DEV_SPEC_COMMERCIAL_APPLIANCE_v1.9.1 (P3-02a OTA Scheduler)
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ota", tags=["ota-updates"])

# =============================================================================
# Import OTA Service
# =============================================================================

try:
    from services.ota_service import (
        get_ota_status,
        check_updates,
        apply_update,
        rollback_update,
        get_current_version,
        UpdateInfo,
        UpdateResult,
        UpdateStatus
    )
    OTA_AVAILABLE = True
except ImportError as e:
    logger.warning(f"OTA service not available: {e}")
    OTA_AVAILABLE = False

# Import scheduler (v1.9.1)
try:
    from services.ota_scheduler import (
        ota_scheduler,
        get_scheduler_status,
        start_scheduler,
        stop_scheduler
    )
    from services.ota_safety import (
        run_all_safety_checks,
        is_safe_to_update
    )
    SCHEDULER_AVAILABLE = True
except ImportError as e:
    logger.warning(f"OTA scheduler not available: {e}")
    SCHEDULER_AVAILABLE = False


# =============================================================================
# Request/Response Models
# =============================================================================

class UpdateCheckResponse(BaseModel):
    """Response for update check."""
    available: bool
    current_version: str
    latest_version: str
    release_notes: Optional[str] = None
    download_url: Optional[str] = None
    size_bytes: Optional[int] = None
    release_date: Optional[str] = None
    breaking_changes: bool = False


class UpdateApplyRequest(BaseModel):
    """Request to apply update."""
    version: Optional[str] = None
    force: bool = False


class UpdateResultResponse(BaseModel):
    """Response for update operations."""
    success: bool
    status: str
    message: str
    previous_version: Optional[str] = None
    new_version: Optional[str] = None
    rollback_available: bool = False


class OTAStatusResponse(BaseModel):
    """OTA system status response."""
    status: str
    current_version: str
    build_date: str
    update_method: str
    last_check: Optional[str] = None
    update_available: bool = False
    latest_version: Optional[str] = None
    ota_enabled: bool = True


# =============================================================================
# API Endpoints
# =============================================================================

@router.get("/status", response_model=OTAStatusResponse)
async def get_status():
    """
    Get OTA system status.

    GET /api/ota/status

    Returns current version, update method, and last check time.
    """
    if not OTA_AVAILABLE:
        return OTAStatusResponse(
            status="unavailable",
            current_version="unknown",
            build_date="unknown",
            update_method="manual",
            ota_enabled=False
        )

    status = get_ota_status()
    return OTAStatusResponse(
        status=status['status'],
        current_version=status['current_version'],
        build_date=status['build_date'],
        update_method=status['update_method'],
        last_check=status.get('last_check'),
        update_available=status.get('update_available', False),
        latest_version=status.get('latest_version'),
        ota_enabled=True
    )


@router.get("/version")
async def get_version():
    """
    Get current version information.

    GET /api/ota/version
    """
    if not OTA_AVAILABLE:
        return {
            "version": "unknown",
            "build_date": "unknown",
            "commit_hash": None,
            "channel": "unknown"
        }

    version = get_current_version()
    return {
        "version": version.version,
        "build_date": version.build_date,
        "commit_hash": version.commit_hash,
        "channel": version.channel
    }


@router.get("/check", response_model=UpdateCheckResponse)
async def check_for_updates(
    channel: str = Query("stable", description="Update channel: stable, beta, dev")
):
    """
    Check for available updates.

    GET /api/ota/check?channel=stable

    Contacts update server to check for new versions.
    """
    if not OTA_AVAILABLE:
        raise HTTPException(status_code=503, detail="OTA service not available")

    try:
        update_info = await check_updates(channel)
        return UpdateCheckResponse(
            available=update_info.available,
            current_version=update_info.current_version,
            latest_version=update_info.latest_version,
            release_notes=update_info.release_notes,
            download_url=update_info.download_url,
            size_bytes=update_info.size_bytes,
            release_date=update_info.release_date,
            breaking_changes=update_info.breaking_changes
        )
    except Exception as e:
        logger.error(f"Update check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/apply", response_model=UpdateResultResponse)
async def apply_update_endpoint(
    request: UpdateApplyRequest,
    background_tasks: BackgroundTasks
):
    """
    Apply available update.

    POST /api/ota/apply
    {
        "version": "2.5.0",  // optional, uses latest if not specified
        "force": false       // force update even if same version
    }

    This endpoint triggers the update process. For Docker deployments,
    this pulls the new image and signals for container restart.
    For binary deployments, this downloads and installs the new binary.
    """
    if not OTA_AVAILABLE:
        raise HTTPException(status_code=503, detail="OTA service not available")

    try:
        result = apply_update(request.version)
        return UpdateResultResponse(
            success=result.success,
            status=result.status.value,
            message=result.message,
            previous_version=result.previous_version,
            new_version=result.new_version,
            rollback_available=result.rollback_available
        )
    except Exception as e:
        logger.error(f"Update application failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rollback", response_model=UpdateResultResponse)
async def rollback_endpoint():
    """
    Rollback to previous version.

    POST /api/ota/rollback

    Reverts to the previously installed version.
    Only available if a backup exists from the last update.
    """
    if not OTA_AVAILABLE:
        raise HTTPException(status_code=503, detail="OTA service not available")

    try:
        result = rollback_update()
        return UpdateResultResponse(
            success=result.success,
            status=result.status.value,
            message=result.message,
            previous_version=result.previous_version,
            new_version=result.new_version,
            rollback_available=False
        )
    except Exception as e:
        logger.error(f"Rollback failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history")
async def get_update_history():
    """
    Get update history.

    GET /api/ota/history

    Returns list of past updates and rollbacks.
    """
    # TODO: Implement update history tracking
    return {
        "history": [],
        "message": "Update history tracking not yet implemented"
    }


# =============================================================================
# Health Check Integration
# =============================================================================

@router.get("/health")
async def ota_health():
    """
    OTA subsystem health check.

    GET /api/ota/health
    """
    return {
        "status": "healthy",
        "ota_available": OTA_AVAILABLE,
        "scheduler_available": SCHEDULER_AVAILABLE if 'SCHEDULER_AVAILABLE' in dir() else False,
        "update_method": get_ota_status().get('update_method') if OTA_AVAILABLE else "unknown"
    }


# =============================================================================
# Scheduler Endpoints (v1.9.1)
# =============================================================================

@router.get("/scheduler/status")
async def get_scheduler_status_endpoint():
    """
    Get OTA scheduler status.

    GET /api/ota/scheduler/status

    Returns scheduler state including:
    - running: Is scheduler active
    - auto_update_enabled: Will updates be applied automatically
    - last_check: Last update check timestamp
    - pending_update: Update waiting to be applied
    """
    if not SCHEDULER_AVAILABLE:
        raise HTTPException(status_code=503, detail="OTA scheduler not available")

    return get_scheduler_status()


@router.post("/scheduler/start")
async def start_scheduler_endpoint():
    """
    Start the OTA scheduler.

    POST /api/ota/scheduler/start

    Starts background scheduler that periodically checks for updates.
    """
    if not SCHEDULER_AVAILABLE:
        raise HTTPException(status_code=503, detail="OTA scheduler not available")

    await ota_scheduler.start()
    return {"success": True, "message": "Scheduler started"}


@router.post("/scheduler/stop")
async def stop_scheduler_endpoint():
    """
    Stop the OTA scheduler.

    POST /api/ota/scheduler/stop

    Stops background scheduler. Manual update checks still work.
    """
    if not SCHEDULER_AVAILABLE:
        raise HTTPException(status_code=503, detail="OTA scheduler not available")

    await ota_scheduler.stop()
    return {"success": True, "message": "Scheduler stopped"}


@router.post("/scheduler/check-now")
async def manual_check_endpoint():
    """
    Manually trigger update check.

    POST /api/ota/scheduler/check-now

    Checks for updates immediately without waiting for next scheduled check.
    """
    if not SCHEDULER_AVAILABLE:
        raise HTTPException(status_code=503, detail="OTA scheduler not available")

    result = await ota_scheduler.check_now()
    return result


@router.post("/scheduler/apply-now")
async def manual_apply_endpoint(version: Optional[str] = None):
    """
    Manually trigger update application.

    POST /api/ota/scheduler/apply-now

    Applies pending update immediately (bypasses time window).
    Still respects active case guard - will not update during surgery.
    """
    if not SCHEDULER_AVAILABLE:
        raise HTTPException(status_code=503, detail="OTA scheduler not available")

    result = await ota_scheduler.apply_now(version)

    if not result.get('success'):
        raise HTTPException(status_code=400, detail=result.get('error'))

    return result


@router.get("/safety/check")
async def safety_check_endpoint():
    """
    Run safety checks without applying update.

    GET /api/ota/safety/check

    Returns detailed safety check report including:
    - Active case guard status
    - Time validity
    - Update window
    - System load
    """
    if not SCHEDULER_AVAILABLE:
        raise HTTPException(status_code=503, detail="OTA scheduler not available")

    # Run quick synchronous check
    safe, reason = is_safe_to_update()

    return {
        "safe_to_update": safe,
        "reason": reason,
        "checks": {
            "active_cases": "checked",
            "time_validity": "checked",
            "system_load": "checked"
        }
    }


@router.get("/safety/full-check")
async def full_safety_check_endpoint(
    new_version: str = Query("1.0.0", description="Version to check"),
    current_version: str = Query("1.0.0", description="Current version")
):
    """
    Run comprehensive safety checks.

    GET /api/ota/safety/full-check?new_version=2.0.0&current_version=1.5.0

    Returns complete safety report with all checks.
    """
    if not SCHEDULER_AVAILABLE:
        raise HTTPException(status_code=503, detail="OTA scheduler not available")

    report = await run_all_safety_checks(
        new_version=new_version,
        current_version=current_version
    )

    return {
        "safe_to_update": report.safe_to_update,
        "checks": report.checks,
        "blocking_reasons": report.blocking_reasons,
        "warnings": report.warnings,
        "timestamp": report.timestamp.isoformat()
    }
