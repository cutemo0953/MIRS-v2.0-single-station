"""
xIRS Secure Data Exchange Protocol - Crypto Engine
Handles key management, encryption, and signing of secure envelopes.

Security Architecture:
- Signing: Ed25519 (via nacl.signing)
- Encryption: NaCl Box (Curve25519 + XSalsa20 + Poly1305)
- Canonical String: Deterministic TBS format to avoid JSON serialization issues
"""

import json
import os
import hashlib
import base64
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, Dict, Any
import uuid

from nacl.signing import SigningKey, VerifyKey
from nacl.public import PrivateKey, PublicKey, Box
from nacl.encoding import Base64Encoder
from nacl.exceptions import CryptoError

from .models import (
    SecureEnvelope,
    EnvelopeHeader,
    TrustedKey,
    TrustedKeysRegistry,
    DecryptedPayload,
)


class KeyManager:
    """
    Manages cryptographic keys for a station.

    Key files:
    - station.private: Ed25519 signing key (PROTECT THIS!)
    - station.public: Ed25519 verify key (share with others)
    - station.encrypt.private: Curve25519 private key for decryption
    - station.encrypt.public: Curve25519 public key for encryption
    - trusted_keys.json: Registry of trusted station public keys
    """

    def __init__(self, security_dir: str = "data/security"):
        self.security_dir = Path(security_dir)
        self.security_dir.mkdir(parents=True, exist_ok=True)

        # Key file paths
        self.signing_private_path = self.security_dir / "station.private"
        self.signing_public_path = self.security_dir / "station.public"
        self.encrypt_private_path = self.security_dir / "station.encrypt.private"
        self.encrypt_public_path = self.security_dir / "station.encrypt.public"
        self.trusted_keys_path = self.security_dir / "trusted_keys.json"

        # Cached keys (loaded lazily)
        self._signing_key: Optional[SigningKey] = None
        self._verify_key: Optional[VerifyKey] = None
        self._encrypt_private: Optional[PrivateKey] = None
        self._encrypt_public: Optional[PublicKey] = None
        self._trusted_registry: Optional[TrustedKeysRegistry] = None

    def generate_keys(self, station_id: str) -> Dict[str, str]:
        """
        Generate new key pairs for this station.
        WARNING: This will overwrite existing keys!

        Returns dict with public key info for sharing.
        """
        # Generate Ed25519 signing key
        signing_key = SigningKey.generate()
        verify_key = signing_key.verify_key

        # Generate Curve25519 encryption key
        encrypt_private = PrivateKey.generate()
        encrypt_public = encrypt_private.public_key

        # Save private keys (with restrictive permissions)
        self._write_key_file(
            self.signing_private_path,
            signing_key.encode(encoder=Base64Encoder).decode()
        )
        self._write_key_file(
            self.encrypt_private_path,
            encrypt_private.encode(encoder=Base64Encoder).decode()
        )

        # Save public keys
        verify_key_b64 = verify_key.encode(encoder=Base64Encoder).decode()
        encrypt_pub_b64 = encrypt_public.encode(encoder=Base64Encoder).decode()

        self.signing_public_path.write_text(verify_key_b64)
        self.encrypt_public_path.write_text(encrypt_pub_b64)

        # Calculate fingerprint
        fingerprint = self._calculate_fingerprint(verify_key_b64)

        # Cache the keys
        self._signing_key = signing_key
        self._verify_key = verify_key
        self._encrypt_private = encrypt_private
        self._encrypt_public = encrypt_public

        return {
            "station_id": station_id,
            "signing_public_key": verify_key_b64,
            "encrypt_public_key": encrypt_pub_b64,
            "fingerprint": fingerprint,
            "generated_at": datetime.now().isoformat(),
        }

    def _write_key_file(self, path: Path, content: str) -> None:
        """Write a key file with restrictive permissions (owner read/write only)."""
        path.write_text(content)
        os.chmod(path, 0o600)

    def _calculate_fingerprint(self, public_key_b64: str) -> str:
        """Calculate SHA256 fingerprint of a public key."""
        key_bytes = base64.b64decode(public_key_b64)
        digest = hashlib.sha256(key_bytes).hexdigest()
        # Format as colon-separated pairs for readability
        return ':'.join(digest[i:i+2] for i in range(0, 16, 2))

    def load_signing_key(self) -> SigningKey:
        """Load the station's Ed25519 signing key."""
        if self._signing_key is None:
            if not self.signing_private_path.exists():
                raise FileNotFoundError(
                    f"Signing key not found at {self.signing_private_path}. "
                    "Run generate_keys() first."
                )
            key_b64 = self.signing_private_path.read_text().strip()
            self._signing_key = SigningKey(key_b64, encoder=Base64Encoder)
        return self._signing_key

    def load_verify_key(self) -> VerifyKey:
        """Load the station's Ed25519 verify (public) key."""
        if self._verify_key is None:
            if not self.signing_public_path.exists():
                raise FileNotFoundError(
                    f"Public key not found at {self.signing_public_path}. "
                    "Run generate_keys() first."
                )
            key_b64 = self.signing_public_path.read_text().strip()
            self._verify_key = VerifyKey(key_b64, encoder=Base64Encoder)
        return self._verify_key

    def load_encrypt_private(self) -> PrivateKey:
        """Load the station's Curve25519 private key for decryption."""
        if self._encrypt_private is None:
            if not self.encrypt_private_path.exists():
                raise FileNotFoundError(
                    f"Encryption private key not found at {self.encrypt_private_path}. "
                    "Run generate_keys() first."
                )
            key_b64 = self.encrypt_private_path.read_text().strip()
            self._encrypt_private = PrivateKey(key_b64, encoder=Base64Encoder)
        return self._encrypt_private

    def load_encrypt_public(self) -> PublicKey:
        """Load the station's Curve25519 public key."""
        if self._encrypt_public is None:
            if not self.encrypt_public_path.exists():
                raise FileNotFoundError(
                    f"Encryption public key not found at {self.encrypt_public_path}. "
                    "Run generate_keys() first."
                )
            key_b64 = self.encrypt_public_path.read_text().strip()
            self._encrypt_public = PublicKey(key_b64, encoder=Base64Encoder)
        return self._encrypt_public

    def get_station_info(self) -> Dict[str, str]:
        """Get this station's public key info for sharing."""
        verify_key = self.load_verify_key()
        encrypt_public = self.load_encrypt_public()

        verify_b64 = verify_key.encode(encoder=Base64Encoder).decode()
        encrypt_b64 = encrypt_public.encode(encoder=Base64Encoder).decode()

        return {
            "signing_public_key": verify_b64,
            "encrypt_public_key": encrypt_b64,
            "fingerprint": self._calculate_fingerprint(verify_b64),
        }

    # =========================================================================
    # Trusted Keys Registry
    # =========================================================================

    def load_trusted_keys(self) -> TrustedKeysRegistry:
        """Load the trusted keys registry."""
        if self._trusted_registry is None:
            if self.trusted_keys_path.exists():
                data = json.loads(self.trusted_keys_path.read_text())
                self._trusted_registry = TrustedKeysRegistry(keys={
                    k: TrustedKey(**v) for k, v in data.get("keys", {}).items()
                })
            else:
                self._trusted_registry = TrustedKeysRegistry()
        return self._trusted_registry

    def save_trusted_keys(self) -> None:
        """Save the trusted keys registry to disk."""
        if self._trusted_registry is None:
            return
        data = {
            "keys": {
                k: v.model_dump() for k, v in self._trusted_registry.keys.items()
            }
        }
        self.trusted_keys_path.write_text(json.dumps(data, indent=2))

    def add_trusted_station(
        self,
        station_id: str,
        signing_public_key: str,
        encrypt_public_key: str,
        station_name: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> TrustedKey:
        """
        Add a station to the trusted keys registry.

        Args:
            station_id: Unique station identifier
            signing_public_key: Base64 Ed25519 public key for signature verification
            encrypt_public_key: Base64 Curve25519 public key for encryption
            station_name: Optional human-readable name
            notes: Optional admin notes
        """
        registry = self.load_trusted_keys()
        fingerprint = self._calculate_fingerprint(signing_public_key)

        trusted_key = TrustedKey(
            public_key=signing_public_key,
            signing_key=encrypt_public_key,
            fingerprint=fingerprint,
            added_at=int(datetime.now().timestamp()),
            station_name=station_name,
            notes=notes,
        )

        registry.add_key(station_id, trusted_key)
        self.save_trusted_keys()

        return trusted_key

    def get_trusted_key(self, station_id: str) -> Optional[TrustedKey]:
        """Get a trusted station's key info."""
        registry = self.load_trusted_keys()
        return registry.get_key(station_id)

    def remove_trusted_station(self, station_id: str) -> bool:
        """Remove a station from trusted keys. Returns True if existed."""
        registry = self.load_trusted_keys()
        result = registry.remove_key(station_id)
        if result:
            self.save_trusted_keys()
        return result

    def list_trusted_stations(self) -> list:
        """List all trusted station IDs."""
        registry = self.load_trusted_keys()
        return registry.list_stations()


class SecureEnvelopeBuilder:
    """
    Builds secure envelopes with encryption and signing.

    Workflow (Encrypt-then-Sign):
    1. Encrypt payload using recipient's public key
    2. Build canonical TBS (To-Be-Signed) string
    3. Sign the TBS string with sender's private key
    4. Package into SecureEnvelope
    """

    def __init__(self, key_manager: KeyManager, station_id: str):
        self.key_manager = key_manager
        self.station_id = station_id

    def build_envelope(
        self,
        payload: Dict[str, Any],
        recipient_id: str,
        data_type: str = "INVENTORY_TRANSFER",
    ) -> SecureEnvelope:
        """
        Build a secure envelope for the given payload.

        Args:
            payload: The data to encrypt and send
            recipient_id: Target station ID (must be in trusted keys)
            data_type: Type of payload (for routing/handling)

        Returns:
            SecureEnvelope ready for serialization to .xirs file
        """
        # 1. Get recipient's encryption public key
        trusted_key = self.key_manager.get_trusted_key(recipient_id)
        if trusted_key is None:
            raise ValueError(
                f"Recipient '{recipient_id}' not found in trusted keys. "
                "Add them first with key_manager.add_trusted_station()"
            )

        if not trusted_key.signing_key:
            raise ValueError(
                f"Recipient '{recipient_id}' has no encryption public key registered."
            )

        # 2. Prepare payload with schema version
        wrapped_payload = DecryptedPayload(
            schema_version="1.0",
            data_type=data_type,
            data=payload,
            created_at=datetime.now().isoformat(),
        )
        payload_bytes = json.dumps(wrapped_payload.model_dump()).encode('utf-8')

        # 3. Encrypt payload using NaCl Box
        recipient_encrypt_key = PublicKey(trusted_key.signing_key, encoder=Base64Encoder)
        sender_encrypt_private = self.key_manager.load_encrypt_private()

        box = Box(sender_encrypt_private, recipient_encrypt_key)
        encrypted = box.encrypt(payload_bytes)

        # Split nonce and ciphertext
        nonce = encrypted.nonce
        ciphertext = encrypted.ciphertext

        # Encode to Base64
        nonce_b64 = base64.urlsafe_b64encode(nonce).decode()
        ciphertext_b64 = base64.urlsafe_b64encode(ciphertext).decode()

        # 4. Build envelope header
        envelope_id = str(uuid.uuid4())
        timestamp = int(datetime.now().timestamp())

        header = EnvelopeHeader(
            version="2.0",
            sender_id=self.station_id,
            recipient_id=recipient_id,
            timestamp=timestamp,
            data_type=data_type,
        )

        # 5. Build canonical TBS string
        tbs_string = self._build_tbs_string(
            sender_id=self.station_id,
            recipient_id=recipient_id,
            envelope_id=envelope_id,
            timestamp=timestamp,
            ciphertext_b64=ciphertext_b64,
        )

        # 6. Sign the TBS string
        signing_key = self.key_manager.load_signing_key()
        signed = signing_key.sign(tbs_string.encode('utf-8'))
        signature_b64 = base64.urlsafe_b64encode(signed.signature).decode()

        # 7. Assemble envelope
        envelope = SecureEnvelope(
            envelope_id=envelope_id,
            header=header,
            payload_encrypted=ciphertext_b64,
            nonce=nonce_b64,
            signature=signature_b64,
        )

        return envelope

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

        Format: "{sender}|{recipient}|{uuid}|{timestamp}|{ciphertext}"

        This deterministic format avoids all JSON canonicalization issues.
        """
        return f"{sender_id}|{recipient_id}|{envelope_id}|{timestamp}|{ciphertext_b64}"

    def envelope_to_file(self, envelope: SecureEnvelope, output_path: str) -> str:
        """
        Write envelope to a .xirs file.

        Args:
            envelope: The secure envelope to write
            output_path: Destination path (will add .xirs extension if missing)

        Returns:
            The actual file path written
        """
        if not output_path.endswith('.xirs'):
            output_path = f"{output_path}.xirs"

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        envelope_dict = envelope.model_dump()
        envelope_dict['header'] = envelope.header.model_dump()

        path.write_text(json.dumps(envelope_dict, indent=2))

        return str(path)

    @staticmethod
    def envelope_from_file(file_path: str) -> SecureEnvelope:
        """
        Read an envelope from a .xirs file.

        Args:
            file_path: Path to the .xirs file

        Returns:
            Parsed SecureEnvelope
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Envelope file not found: {file_path}")

        data = json.loads(path.read_text())

        # Reconstruct header
        header = EnvelopeHeader(**data['header'])

        return SecureEnvelope(
            envelope_id=data['envelope_id'],
            header=header,
            payload_encrypted=data['payload_encrypted'],
            nonce=data['nonce'],
            signature=data['signature'],
        )
