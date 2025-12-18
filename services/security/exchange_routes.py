"""
xIRS Secure Data Exchange Protocol - FastAPI Routes
Provides REST API endpoints for secure data import/export.

Endpoints:
- POST /api/exchange/export     - Create encrypted envelope
- POST /api/exchange/import     - Verify and import data
- GET  /api/exchange/keys       - Get station public keys
- GET  /api/exchange/trusted    - List trusted stations
- POST /api/exchange/trust      - Add trusted station
- DELETE /api/exchange/trust/{station_id} - Remove trusted station
- POST /api/exchange/init       - Initialize station keys
"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from pathlib import Path
from datetime import datetime
import tempfile
import json
import os

from .crypto_engine import KeyManager, SecureEnvelopeBuilder
from .envelope_verifier import EnvelopeVerifier, VerificationError
from .models import SecureEnvelope, TrustedKey


# ============================================================================
# Configuration
# ============================================================================

# Default paths - can be overridden via environment variables
SECURITY_DIR = os.environ.get("XIRS_SECURITY_DIR", "data/security")
STATION_ID = os.environ.get("XIRS_STATION_ID", "UNNAMED-STATION")

# Initialize key manager (lazy loading)
_key_manager: Optional[KeyManager] = None
_station_id: str = STATION_ID


def get_key_manager() -> KeyManager:
    """Get or create the key manager instance."""
    global _key_manager
    if _key_manager is None:
        _key_manager = KeyManager(SECURITY_DIR)
    return _key_manager


def get_station_id() -> str:
    """Get the current station ID."""
    return _station_id


def set_station_id(station_id: str) -> None:
    """Set the station ID (call during app init)."""
    global _station_id
    _station_id = station_id


# ============================================================================
# Request/Response Models
# ============================================================================

class InitKeysRequest(BaseModel):
    """Request to initialize station keys."""
    station_id: str = Field(..., description="Unique station identifier")
    force: bool = Field(False, description="Overwrite existing keys if True")


class InitKeysResponse(BaseModel):
    """Response after initializing keys."""
    success: bool
    station_id: str
    signing_public_key: str
    encrypt_public_key: str
    fingerprint: str
    message: str


class ExportRequest(BaseModel):
    """Request to export data as encrypted envelope."""
    recipient_id: str = Field(..., description="Target station ID")
    data_type: str = Field("INVENTORY_TRANSFER", description="Type of data")
    payload: Dict[str, Any] = Field(..., description="Data to encrypt and send")


class ExportResponse(BaseModel):
    """Response after creating export envelope."""
    success: bool
    envelope_id: str
    file_name: str
    recipient_id: str
    data_type: str
    message: str


class ImportResponse(BaseModel):
    """Response after importing and verifying envelope."""
    success: bool
    envelope_id: str
    sender_id: str
    sender_fingerprint: str
    data_type: str
    payload: Dict[str, Any]
    verification_info: Dict[str, Any]
    message: str


class AddTrustRequest(BaseModel):
    """Request to add a trusted station."""
    station_id: str = Field(..., description="Station ID to trust")
    signing_public_key: str = Field(..., description="Ed25519 public key (Base64)")
    encrypt_public_key: str = Field(..., description="Curve25519 public key (Base64)")
    station_name: Optional[str] = Field(None, description="Human-readable name")
    notes: Optional[str] = Field(None, description="Admin notes")


class TrustedStationInfo(BaseModel):
    """Information about a trusted station."""
    station_id: str
    fingerprint: str
    station_name: Optional[str]
    added_at: int
    notes: Optional[str]


class StationKeysResponse(BaseModel):
    """Response with station's public keys."""
    station_id: str
    signing_public_key: str
    encrypt_public_key: str
    fingerprint: str
    share_instructions: str


# ============================================================================
# Router
# ============================================================================

router = APIRouter(prefix="/api/exchange", tags=["Secure Exchange"])


@router.post("/init", response_model=InitKeysResponse)
async def initialize_keys(request: InitKeysRequest):
    """
    Initialize cryptographic keys for this station.

    This creates:
    - Ed25519 signing key pair (for signatures)
    - Curve25519 encryption key pair (for encryption)

    WARNING: If force=True, existing keys will be overwritten!
    """
    key_mgr = get_key_manager()

    # Check if keys already exist
    if key_mgr.signing_private_path.exists() and not request.force:
        raise HTTPException(
            status_code=400,
            detail="Keys already exist. Use force=true to overwrite (DANGEROUS!)"
        )

    try:
        info = key_mgr.generate_keys(request.station_id)
        set_station_id(request.station_id)

        return InitKeysResponse(
            success=True,
            station_id=request.station_id,
            signing_public_key=info['signing_public_key'],
            encrypt_public_key=info['encrypt_public_key'],
            fingerprint=info['fingerprint'],
            message=f"Keys generated successfully. Share your public keys with trusted stations."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Key generation failed: {str(e)}")


@router.get("/keys", response_model=StationKeysResponse)
async def get_station_keys():
    """
    Get this station's public keys for sharing with other stations.

    Share these keys with stations you want to exchange data with.
    They need to add your keys to their trusted registry.
    """
    key_mgr = get_key_manager()

    try:
        info = key_mgr.get_station_info()
        return StationKeysResponse(
            station_id=get_station_id(),
            signing_public_key=info['signing_public_key'],
            encrypt_public_key=info['encrypt_public_key'],
            fingerprint=info['fingerprint'],
            share_instructions=(
                "Share these keys with other stations. "
                "They should verify the fingerprint matches before trusting."
            )
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Keys not initialized. Call POST /api/exchange/init first."
        )


@router.get("/trusted", response_model=List[TrustedStationInfo])
async def list_trusted_stations():
    """List all trusted stations."""
    key_mgr = get_key_manager()
    registry = key_mgr.load_trusted_keys()

    result = []
    for station_id, key in registry.keys.items():
        result.append(TrustedStationInfo(
            station_id=station_id,
            fingerprint=key.fingerprint,
            station_name=key.station_name,
            added_at=key.added_at,
            notes=key.notes,
        ))

    return result


@router.post("/trust")
async def add_trusted_station(request: AddTrustRequest):
    """
    Add a station to the trusted registry.

    You need the station's public keys (get them from their /api/exchange/keys endpoint).
    Verify the fingerprint matches before trusting!
    """
    key_mgr = get_key_manager()

    try:
        trusted_key = key_mgr.add_trusted_station(
            station_id=request.station_id,
            signing_public_key=request.signing_public_key,
            encrypt_public_key=request.encrypt_public_key,
            station_name=request.station_name,
            notes=request.notes,
        )

        return {
            "success": True,
            "station_id": request.station_id,
            "fingerprint": trusted_key.fingerprint,
            "message": f"Station '{request.station_id}' added to trusted registry."
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to add trusted station: {str(e)}")


@router.delete("/trust/{station_id}")
async def remove_trusted_station(station_id: str):
    """Remove a station from the trusted registry."""
    key_mgr = get_key_manager()

    if key_mgr.remove_trusted_station(station_id):
        return {
            "success": True,
            "message": f"Station '{station_id}' removed from trusted registry."
        }
    else:
        raise HTTPException(
            status_code=404,
            detail=f"Station '{station_id}' not found in trusted registry."
        )


@router.post("/export", response_model=ExportResponse)
async def export_data(request: ExportRequest):
    """
    Create an encrypted envelope for the specified recipient.

    The envelope will be signed with this station's private key
    and encrypted with the recipient's public key.

    Returns the envelope file for USB transfer.
    """
    key_mgr = get_key_manager()
    station_id = get_station_id()

    # Check keys are initialized
    try:
        key_mgr.load_signing_key()
    except FileNotFoundError:
        raise HTTPException(
            status_code=400,
            detail="Keys not initialized. Call POST /api/exchange/init first."
        )

    # Check recipient is trusted
    if not key_mgr.get_trusted_key(request.recipient_id):
        raise HTTPException(
            status_code=400,
            detail=f"Recipient '{request.recipient_id}' not in trusted registry. Add them first."
        )

    try:
        builder = SecureEnvelopeBuilder(key_mgr, station_id)
        envelope = builder.build_envelope(
            payload=request.payload,
            recipient_id=request.recipient_id,
            data_type=request.data_type,
        )

        # Save to exports directory
        exports_dir = Path("exports/xirs")
        exports_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{request.data_type}_{request.recipient_id}_{timestamp}.xirs"
        filepath = exports_dir / filename

        builder.envelope_to_file(envelope, str(filepath))

        return ExportResponse(
            success=True,
            envelope_id=envelope.envelope_id,
            file_name=filename,
            recipient_id=request.recipient_id,
            data_type=request.data_type,
            message=f"Envelope created. Copy {filename} to USB for transfer."
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")


@router.get("/export/{filename}")
async def download_export(filename: str):
    """Download a previously created export file."""
    filepath = Path("exports/xirs") / filename

    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"Export file not found: {filename}")

    return FileResponse(
        path=str(filepath),
        filename=filename,
        media_type="application/json"
    )


@router.post("/import", response_model=ImportResponse)
async def import_data(file: UploadFile = File(...)):
    """
    Import and verify an encrypted envelope.

    The envelope will be:
    1. Checked against the trusted registry
    2. Verified for signature validity
    3. Checked for replay attacks
    4. Decrypted if all checks pass

    Returns the decrypted payload if successful.
    """
    key_mgr = get_key_manager()
    station_id = get_station_id()

    # Check keys are initialized
    try:
        key_mgr.load_signing_key()
    except FileNotFoundError:
        raise HTTPException(
            status_code=400,
            detail="Keys not initialized. Call POST /api/exchange/init first."
        )

    # Read uploaded file
    try:
        content = await file.read()
        envelope_dict = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON in uploaded file")

    # Parse envelope
    try:
        from .models import EnvelopeHeader
        header = EnvelopeHeader(**envelope_dict['header'])
        envelope = SecureEnvelope(
            envelope_id=envelope_dict['envelope_id'],
            header=header,
            payload_encrypted=envelope_dict['payload_encrypted'],
            nonce=envelope_dict['nonce'],
            signature=envelope_dict['signature'],
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid envelope format: {str(e)}")

    # Verify and decrypt
    try:
        verifier = EnvelopeVerifier(key_mgr, station_id)
        payload, verify_info = verifier.verify_and_decrypt(envelope)

        return ImportResponse(
            success=True,
            envelope_id=envelope.envelope_id,
            sender_id=envelope.header.sender_id,
            sender_fingerprint=verify_info.get('sender_fingerprint', ''),
            data_type=envelope.header.data_type,
            payload=payload.data,
            verification_info=verify_info,
            message="Envelope verified and decrypted successfully."
        )
    except VerificationError as e:
        raise HTTPException(status_code=403, detail=f"Verification failed: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")


@router.get("/stats")
async def get_exchange_stats():
    """Get statistics about processed envelopes."""
    key_mgr = get_key_manager()
    station_id = get_station_id()

    try:
        verifier = EnvelopeVerifier(key_mgr, station_id)
        stats = verifier.get_replay_stats()

        return {
            "station_id": station_id,
            "trusted_stations": len(key_mgr.list_trusted_stations()),
            "processed_envelopes": stats.get('total_processed', 0),
            "by_sender": stats.get('by_sender', {}),
        }
    except Exception as e:
        return {
            "station_id": station_id,
            "error": str(e),
        }


@router.post("/cleanup")
async def cleanup_old_records(days: int = 30):
    """Clean up old processed envelope records."""
    key_mgr = get_key_manager()
    station_id = get_station_id()

    try:
        verifier = EnvelopeVerifier(key_mgr, station_id)
        removed = verifier.cleanup_old_envelopes(days)

        return {
            "success": True,
            "removed_count": removed,
            "message": f"Removed {removed} records older than {days} days."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")
