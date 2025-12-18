"""
xIRS Secure Data Exchange Protocol - Envelope Verifier
Handles verification, decryption, and replay protection of secure envelopes.

Verification Steps:
1. Structural validation (valid JSON, all fields present)
2. Trust check (sender in trusted_keys, recipient is me)
3. Replay check (timestamp not expired, envelope_id not seen)
4. Signature verification (reconstruct TBS, verify with sender's public key)
5. Decryption (use my private key + sender's public key)
"""

import json
import base64
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple

from nacl.signing import VerifyKey
from nacl.public import PrivateKey, PublicKey, Box
from nacl.encoding import Base64Encoder
from nacl.exceptions import BadSignatureError, CryptoError

from .models import SecureEnvelope, DecryptedPayload
from .crypto_engine import KeyManager


class ReplayProtector:
    """
    Tracks processed envelope IDs to prevent replay attacks.
    Uses SQLite for persistent storage.
    """

    def __init__(self, db_path: str = "data/security/processed_envelopes.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the processed envelopes database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS processed_envelopes (
                    envelope_id TEXT PRIMARY KEY,
                    sender_id TEXT NOT NULL,
                    processed_at INTEGER NOT NULL,
                    data_type TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_processed_at
                ON processed_envelopes(processed_at)
            """)
            conn.commit()

    def is_processed(self, envelope_id: str) -> bool:
        """Check if an envelope has already been processed."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM processed_envelopes WHERE envelope_id = ?",
                (envelope_id,)
            )
            return cursor.fetchone() is not None

    def mark_processed(
        self,
        envelope_id: str,
        sender_id: str,
        data_type: str = ""
    ) -> None:
        """Mark an envelope as processed."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO processed_envelopes
                (envelope_id, sender_id, processed_at, data_type)
                VALUES (?, ?, ?, ?)
                """,
                (envelope_id, sender_id, int(datetime.now().timestamp()), data_type)
            )
            conn.commit()

    def cleanup_old_entries(self, days: int = 30) -> int:
        """
        Remove entries older than specified days.
        Returns number of entries removed.
        """
        cutoff = int((datetime.now() - timedelta(days=days)).timestamp())
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM processed_envelopes WHERE processed_at < ?",
                (cutoff,)
            )
            conn.commit()
            return cursor.rowcount

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about processed envelopes."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT COUNT(*), MIN(processed_at), MAX(processed_at) FROM processed_envelopes"
            )
            count, oldest, newest = cursor.fetchone()

            cursor = conn.execute(
                "SELECT sender_id, COUNT(*) FROM processed_envelopes GROUP BY sender_id"
            )
            by_sender = dict(cursor.fetchall())

            return {
                "total_processed": count or 0,
                "oldest_timestamp": oldest,
                "newest_timestamp": newest,
                "by_sender": by_sender,
            }


class VerificationError(Exception):
    """Base exception for verification failures."""
    pass


class TrustError(VerificationError):
    """Raised when sender is not trusted or recipient doesn't match."""
    pass


class ReplayError(VerificationError):
    """Raised when envelope is a replay (already processed or expired)."""
    pass


class SignatureError(VerificationError):
    """Raised when signature verification fails."""
    pass


class DecryptionError(VerificationError):
    """Raised when decryption fails."""
    pass


class EnvelopeVerifier:
    """
    Verifies and decrypts secure envelopes.

    Performs full security validation:
    - Trust verification
    - Replay protection
    - Signature verification
    - Authenticated decryption
    """

    # Default expiry: 7 days
    DEFAULT_EXPIRY_DAYS = 7

    def __init__(
        self,
        key_manager: KeyManager,
        station_id: str,
        expiry_days: int = DEFAULT_EXPIRY_DAYS,
        replay_db_path: Optional[str] = None,
    ):
        self.key_manager = key_manager
        self.station_id = station_id
        self.expiry_days = expiry_days

        db_path = replay_db_path or "data/security/processed_envelopes.db"
        self.replay_protector = ReplayProtector(db_path)

    def verify_and_decrypt(
        self,
        envelope: SecureEnvelope,
        skip_replay_check: bool = False,
    ) -> Tuple[DecryptedPayload, Dict[str, Any]]:
        """
        Verify and decrypt a secure envelope.

        Args:
            envelope: The envelope to verify and decrypt
            skip_replay_check: If True, skip replay protection (for testing only!)

        Returns:
            Tuple of (decrypted_payload, verification_info)

        Raises:
            TrustError: Sender not trusted or recipient mismatch
            ReplayError: Envelope already processed or expired
            SignatureError: Signature verification failed
            DecryptionError: Decryption failed
        """
        verification_info = {
            "envelope_id": envelope.envelope_id,
            "sender_id": envelope.header.sender_id,
            "recipient_id": envelope.header.recipient_id,
            "timestamp": envelope.header.timestamp,
            "data_type": envelope.header.data_type,
            "verified_at": datetime.now().isoformat(),
        }

        # Step 1: Trust Check
        self._verify_trust(envelope, verification_info)

        # Step 2: Replay Check
        if not skip_replay_check:
            self._verify_replay(envelope, verification_info)

        # Step 3: Signature Verification
        self._verify_signature(envelope, verification_info)

        # Step 4: Decryption
        payload = self._decrypt_payload(envelope, verification_info)

        # Step 5: Mark as processed (only if replay check wasn't skipped)
        if not skip_replay_check:
            self.replay_protector.mark_processed(
                envelope.envelope_id,
                envelope.header.sender_id,
                envelope.header.data_type,
            )

        verification_info["success"] = True
        return payload, verification_info

    def _verify_trust(
        self,
        envelope: SecureEnvelope,
        info: Dict[str, Any]
    ) -> None:
        """Verify sender is trusted and recipient matches."""
        # Check recipient is me
        if envelope.header.recipient_id != self.station_id:
            info["error"] = "recipient_mismatch"
            raise TrustError(
                f"Envelope addressed to '{envelope.header.recipient_id}', "
                f"but I am '{self.station_id}'"
            )

        # Check sender is trusted
        trusted_key = self.key_manager.get_trusted_key(envelope.header.sender_id)
        if trusted_key is None:
            info["error"] = "sender_not_trusted"
            raise TrustError(
                f"Sender '{envelope.header.sender_id}' is not in trusted keys registry"
            )

        info["sender_fingerprint"] = trusted_key.fingerprint

    def _verify_replay(
        self,
        envelope: SecureEnvelope,
        info: Dict[str, Any]
    ) -> None:
        """Verify envelope is not expired and not a replay."""
        # Check timestamp expiry
        envelope_time = datetime.fromtimestamp(envelope.header.timestamp)
        expiry_time = datetime.now() - timedelta(days=self.expiry_days)

        if envelope_time < expiry_time:
            age_days = (datetime.now() - envelope_time).days
            info["error"] = "envelope_expired"
            raise ReplayError(
                f"Envelope is {age_days} days old, exceeds {self.expiry_days} day limit"
            )

        # Check if already processed
        if self.replay_protector.is_processed(envelope.envelope_id):
            info["error"] = "replay_detected"
            raise ReplayError(
                f"Envelope '{envelope.envelope_id}' has already been processed"
            )

        info["age_seconds"] = int((datetime.now() - envelope_time).total_seconds())

    def _verify_signature(
        self,
        envelope: SecureEnvelope,
        info: Dict[str, Any]
    ) -> None:
        """Verify the envelope signature."""
        # Get sender's public signing key
        trusted_key = self.key_manager.get_trusted_key(envelope.header.sender_id)
        if not trusted_key:
            raise TrustError("Sender not in trusted keys")

        try:
            verify_key = VerifyKey(trusted_key.public_key, encoder=Base64Encoder)
        except Exception as e:
            info["error"] = "invalid_sender_key"
            raise SignatureError(f"Invalid sender public key: {e}")

        # Reconstruct the canonical TBS string
        tbs_string = self._build_tbs_string(
            sender_id=envelope.header.sender_id,
            recipient_id=envelope.header.recipient_id,
            envelope_id=envelope.envelope_id,
            timestamp=envelope.header.timestamp,
            ciphertext_b64=envelope.payload_encrypted,
        )

        # Decode signature
        try:
            signature = base64.urlsafe_b64decode(envelope.signature)
        except Exception as e:
            info["error"] = "invalid_signature_encoding"
            raise SignatureError(f"Invalid signature encoding: {e}")

        # Verify signature
        try:
            verify_key.verify(tbs_string.encode('utf-8'), signature)
        except BadSignatureError:
            info["error"] = "signature_invalid"
            raise SignatureError(
                "SECURITY ALERT: Signature verification failed! "
                "Envelope may have been tampered with."
            )

        info["signature_valid"] = True

    def _decrypt_payload(
        self,
        envelope: SecureEnvelope,
        info: Dict[str, Any]
    ) -> DecryptedPayload:
        """Decrypt the envelope payload."""
        # Get sender's encryption public key
        trusted_key = self.key_manager.get_trusted_key(envelope.header.sender_id)
        if not trusted_key or not trusted_key.signing_key:
            raise DecryptionError("Sender encryption key not found")

        try:
            sender_encrypt_key = PublicKey(trusted_key.signing_key, encoder=Base64Encoder)
            my_encrypt_private = self.key_manager.load_encrypt_private()
        except Exception as e:
            info["error"] = "key_load_error"
            raise DecryptionError(f"Failed to load encryption keys: {e}")

        # Decode nonce and ciphertext
        try:
            nonce = base64.urlsafe_b64decode(envelope.nonce)
            ciphertext = base64.urlsafe_b64decode(envelope.payload_encrypted)
        except Exception as e:
            info["error"] = "invalid_payload_encoding"
            raise DecryptionError(f"Invalid payload encoding: {e}")

        # Decrypt using NaCl Box
        try:
            box = Box(my_encrypt_private, sender_encrypt_key)
            plaintext = box.decrypt(ciphertext, nonce)
        except CryptoError as e:
            info["error"] = "decryption_failed"
            raise DecryptionError(
                "Decryption failed. Possible causes: "
                "wrong keys, corrupted data, or tampered envelope."
            )

        # Parse payload
        try:
            payload_dict = json.loads(plaintext.decode('utf-8'))
            payload = DecryptedPayload(**payload_dict)
        except Exception as e:
            info["error"] = "payload_parse_error"
            raise DecryptionError(f"Failed to parse decrypted payload: {e}")

        info["decrypted"] = True
        info["payload_schema_version"] = payload.schema_version

        return payload

    def _build_tbs_string(
        self,
        sender_id: str,
        recipient_id: str,
        envelope_id: str,
        timestamp: int,
        ciphertext_b64: str,
    ) -> str:
        """
        Build the canonical To-Be-Signed string.
        Must match the format used in SecureEnvelopeBuilder.
        """
        return f"{sender_id}|{recipient_id}|{envelope_id}|{timestamp}|{ciphertext_b64}"

    def verify_file(
        self,
        file_path: str,
        skip_replay_check: bool = False,
    ) -> Tuple[DecryptedPayload, Dict[str, Any]]:
        """
        Convenience method to verify and decrypt a .xirs file.

        Args:
            file_path: Path to the .xirs file
            skip_replay_check: If True, skip replay protection

        Returns:
            Tuple of (decrypted_payload, verification_info)
        """
        from .crypto_engine import SecureEnvelopeBuilder

        envelope = SecureEnvelopeBuilder.envelope_from_file(file_path)
        return self.verify_and_decrypt(envelope, skip_replay_check)

    def get_replay_stats(self) -> Dict[str, Any]:
        """Get replay protection statistics."""
        return self.replay_protector.get_stats()

    def cleanup_old_envelopes(self, days: int = 30) -> int:
        """Clean up old processed envelope records."""
        return self.replay_protector.cleanup_old_entries(days)
