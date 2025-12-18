"""
xIRS Secure Data Exchange Protocol - Pydantic Models
Defines the strict schema for .xirs envelope files.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, Any, Dict
from datetime import datetime
import re
import uuid


class EnvelopeHeader(BaseModel):
    """Header section of a secure envelope."""
    version: str = Field(default="2.0", description="Protocol version")
    sender_id: str = Field(..., description="Sender station ID (e.g., MIRS-STATION-A)")
    recipient_id: str = Field(..., description="Recipient station ID")
    timestamp: int = Field(..., description="Unix epoch timestamp")
    data_type: str = Field(..., description="Type of payload (e.g., INVENTORY_TRANSFER)")

    @field_validator('sender_id', 'recipient_id')
    @classmethod
    def validate_station_id(cls, v: str) -> str:
        """Validate station ID format - must not contain pipe character."""
        if not re.match(r'^[A-Za-z0-9\-_]+$', v):
            raise ValueError(
                f"Station ID must contain only alphanumeric characters, hyphens, and underscores. Got: {v}"
            )
        if '|' in v:
            raise ValueError("Station ID cannot contain pipe character '|'")
        return v

    @field_validator('data_type')
    @classmethod
    def validate_data_type(cls, v: str) -> str:
        """Validate data type format."""
        valid_types = [
            'INVENTORY_TRANSFER',
            'PERSON_TRANSFER',
            'EVENT_LOG',
            'FULL_BACKUP',
            'PARTIAL_SYNC',
            'COMMAND',
        ]
        if v not in valid_types:
            raise ValueError(f"Invalid data_type. Must be one of: {valid_types}")
        return v


class SecureEnvelope(BaseModel):
    """
    Complete secure envelope structure for .xirs files.

    Security properties:
    - Confidentiality: payload_encrypted using NaCl Box
    - Integrity: signature over canonical TBS string
    - Anti-replay: envelope_id (UUID) + timestamp expiry
    """
    envelope_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique envelope identifier (UUID v4)"
    )
    header: EnvelopeHeader
    payload_encrypted: str = Field(..., description="Base64URL encoded ciphertext")
    nonce: str = Field(..., description="Base64URL encoded nonce for decryption")
    signature: str = Field(..., description="Base64URL Ed25519 signature")

    @field_validator('envelope_id')
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        """Validate envelope_id is a valid UUID."""
        try:
            uuid.UUID(v)
        except ValueError:
            raise ValueError(f"envelope_id must be a valid UUID. Got: {v}")
        return v


class TrustedKey(BaseModel):
    """Entry in the trusted keys registry."""
    public_key: str = Field(..., description="Base64 encoded Ed25519 public key")
    signing_key: Optional[str] = Field(None, description="Base64 encoded Curve25519 public key for encryption")
    fingerprint: str = Field(..., description="Key fingerprint for human verification")
    added_at: int = Field(..., description="Unix timestamp when key was added")
    station_name: Optional[str] = Field(None, description="Human-readable station name")
    notes: Optional[str] = Field(None, description="Admin notes")


class TrustedKeysRegistry(BaseModel):
    """Registry of all trusted station keys."""
    keys: Dict[str, TrustedKey] = Field(default_factory=dict)

    def get_key(self, station_id: str) -> Optional[TrustedKey]:
        """Get a trusted key by station ID."""
        return self.keys.get(station_id)

    def add_key(self, station_id: str, key: TrustedKey) -> None:
        """Add or update a trusted key."""
        self.keys[station_id] = key

    def remove_key(self, station_id: str) -> bool:
        """Remove a trusted key. Returns True if key existed."""
        if station_id in self.keys:
            del self.keys[station_id]
            return True
        return False

    def list_stations(self) -> list:
        """List all trusted station IDs."""
        return list(self.keys.keys())


class DecryptedPayload(BaseModel):
    """Wrapper for decrypted payload with metadata."""
    schema_version: str = Field(default="1.0", description="Payload schema version")
    data_type: str = Field(..., description="Type of data")
    data: Any = Field(..., description="The actual payload data")
    created_at: Optional[str] = Field(None, description="ISO timestamp of creation")
    checksum: Optional[str] = Field(None, description="Optional SHA256 of data for extra verification")
