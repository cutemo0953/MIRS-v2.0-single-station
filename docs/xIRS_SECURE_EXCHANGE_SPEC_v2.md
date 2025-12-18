# xIRS Secure Data Exchange Protocol (XSDEP) v2.0

> **Version:** 2.0 (Enhanced Security)
> **Target Systems:** MIRS / CIRS / HIRS
> **Security Model:** Authenticated Encryption + Digital Signatures + Replay Protection
> **Library:** PyNaCl (libsodium binding)

## Overview

xIRS (Cross-IRS) is a defense-grade secure data exchange protocol designed for offline USB-based data transfer between IRS (Inventory/Resilience System) stations. It ensures:

- **Confidentiality:** Data is encrypted; only the intended recipient can read it
- **Integrity:** Digital signatures detect any tampering
- **Authenticity:** Verified sender identity via trusted key registry
- **Anti-Replay:** Each envelope can only be processed once

## 1. Security Architecture

### 1.1 Cryptographic Primitives

| Purpose | Algorithm | Library |
|---------|-----------|---------|
| Signing | Ed25519 | `nacl.signing` |
| Encryption | Curve25519 + XSalsa20 + Poly1305 | `nacl.public.Box` |
| Key Derivation | Built-in to NaCl | libsodium |

### 1.2 Encrypt-then-Sign Workflow

```
┌─────────────────────────────────────────────────────────────┐
│                    SENDER (Station A)                        │
├─────────────────────────────────────────────────────────────┤
│  1. Prepare JSON payload                                     │
│  2. Encrypt with Recipient's public key (NaCl Box)          │
│  3. Build canonical TBS string:                              │
│     "{sender}|{recipient}|{uuid}|{timestamp}|{ciphertext}"  │
│  4. Sign TBS with Sender's Ed25519 private key              │
│  5. Package into .xirs envelope                              │
└─────────────────────────────────────────────────────────────┘
                           │
                           │ USB Transfer
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                   RECEIVER (Station B)                       │
├─────────────────────────────────────────────────────────────┤
│  1. Structural validation (valid JSON, all fields)          │
│  2. Trust check (sender in registry, recipient = me)        │
│  3. Replay check (not expired, not already processed)       │
│  4. Reconstruct TBS, verify signature with sender's pubkey  │
│  5. Decrypt payload with my private key                      │
│  6. Mark envelope as processed                               │
└─────────────────────────────────────────────────────────────┘
```

### 1.3 The Canonical TBS String

To avoid JSON serialization inconsistencies, we sign a deterministic string:

```
TBS_String = "{sender_id}|{recipient_id}|{envelope_id}|{timestamp}|{base64_ciphertext}"
```

**Important:** Station IDs must not contain the pipe character `|`.

## 2. Data Structures

### 2.1 Envelope Format (.xirs file)

```json
{
  "envelope_id": "550e8400-e29b-41d4-a716-446655440000",
  "header": {
    "version": "2.0",
    "sender_id": "MIRS-STATION-A",
    "recipient_id": "MIRS-STATION-B",
    "timestamp": 1702886400,
    "data_type": "INVENTORY_TRANSFER"
  },
  "payload_encrypted": "8qT5... (Base64URL ciphertext) ...9aB==",
  "nonce": "Xy7... (Base64URL nonce) ...1z",
  "signature": "Op9... (Base64URL Ed25519 signature) ...zQ=="
}
```

### 2.2 Decrypted Payload Structure

```json
{
  "schema_version": "1.0",
  "data_type": "INVENTORY_TRANSFER",
  "data": { /* actual payload */ },
  "created_at": "2024-12-18T10:30:00Z"
}
```

### 2.3 Trusted Keys Registry

Location: `data/security/trusted_keys.json`

```json
{
  "keys": {
    "MIRS-STATION-B": {
      "public_key": "MTA5...",
      "signing_key": "abc123...",
      "fingerprint": "a1:b2:c3:d4:e5:f6:a7:b8",
      "added_at": 1702880000,
      "station_name": "Medical Station B"
    }
  }
}
```

## 3. Key Management

### 3.1 Key Files

| File | Content | Protection |
|------|---------|------------|
| `station.private` | Ed25519 signing key | chmod 600 |
| `station.public` | Ed25519 verify key | Shareable |
| `station.encrypt.private` | Curve25519 private key | chmod 600 |
| `station.encrypt.public` | Curve25519 public key | Shareable |
| `trusted_keys.json` | Trusted station registry | chmod 644 |

### 3.2 Key Exchange Protocol

```
Station A                          Station B
    │                                  │
    │  1. Generate keys                │
    │  2. Share public keys            │
    │     (fingerprint verification)   │
    │ ─────────────────────────────▶   │
    │                                  │
    │   3. Add A to trusted registry   │
    │                                  │
    │  4. Share B's public keys        │
    │ ◀─────────────────────────────   │
    │                                  │
    │  5. Add B to trusted registry    │
    │                                  │
    ▼                                  ▼
   Ready for secure exchange
```

**Fingerprint Verification:** Always verify fingerprints out-of-band (phone, in-person) before trusting a key!

## 4. API Reference

### 4.1 Initialize Keys

```http
POST /api/exchange/init
Content-Type: application/json

{
  "station_id": "MIRS-TAIPEI-01",
  "force": false
}
```

### 4.2 Get Public Keys

```http
GET /api/exchange/keys
```

Response:
```json
{
  "station_id": "MIRS-TAIPEI-01",
  "signing_public_key": "MTA5...",
  "encrypt_public_key": "abc123...",
  "fingerprint": "a1:b2:c3:d4:e5:f6:a7:b8"
}
```

### 4.3 Add Trusted Station

```http
POST /api/exchange/trust
Content-Type: application/json

{
  "station_id": "CIRS-SHELTER-A",
  "signing_public_key": "...",
  "encrypt_public_key": "...",
  "station_name": "Community Shelter A"
}
```

### 4.4 Export Data

```http
POST /api/exchange/export
Content-Type: application/json

{
  "recipient_id": "CIRS-SHELTER-A",
  "data_type": "INVENTORY_TRANSFER",
  "payload": {
    "items": [...],
    "notes": "Emergency supply transfer"
  }
}
```

### 4.5 Import Data

```http
POST /api/exchange/import
Content-Type: multipart/form-data

file: <.xirs file>
```

## 5. Security Considerations

### 5.1 Private Key Protection

- Store private keys with `chmod 600`
- Never transmit private keys over network
- Consider hardware security modules for production
- Backup keys securely (encrypted USB, safe deposit)

### 5.2 Anti-Replay Protection

- Each envelope has a unique UUID
- Envelopes older than 7 days are rejected
- Processed UUIDs are stored in SQLite database
- Database should be periodically cleaned (30+ day old records)

### 5.3 Trust Registry Management

- Verify fingerprints out-of-band before trusting
- Review trusted stations periodically
- Remove compromised/retired stations promptly

### 5.4 No Forward Secrecy

Current design does NOT provide forward secrecy. If a private key is compromised, all past messages encrypted to that key can be decrypted. For highly sensitive applications, consider:

- Key rotation schedules
- Ephemeral keys per session (adds complexity)
- Secure deletion of old private keys

## 6. Data Types

| data_type | Description |
|-----------|-------------|
| `INVENTORY_TRANSFER` | Transfer inventory between stations |
| `PERSON_TRANSFER` | Transfer person records |
| `EVENT_LOG` | Sync event logs |
| `FULL_BACKUP` | Complete database backup |
| `PARTIAL_SYNC` | Incremental sync |
| `COMMAND` | Remote command (with caution) |

## 7. Error Handling

| Error | HTTP Code | Meaning |
|-------|-----------|---------|
| `TrustError` | 403 | Sender not trusted or recipient mismatch |
| `ReplayError` | 403 | Envelope expired or already processed |
| `SignatureError` | 403 | Signature verification failed (TAMPERING!) |
| `DecryptionError` | 403 | Decryption failed |
| Keys not initialized | 400 | Call /api/exchange/init first |

## 8. Implementation Files

```
services/security/
├── __init__.py           # Module exports
├── models.py             # Pydantic data models
├── crypto_engine.py      # KeyManager, SecureEnvelopeBuilder
├── envelope_verifier.py  # EnvelopeVerifier, ReplayProtector
├── exchange_routes.py    # FastAPI router
└── test_crypto.py        # Integration tests
```

## 9. Quick Start

```python
from services.security import (
    KeyManager,
    SecureEnvelopeBuilder,
    EnvelopeVerifier,
)

# Initialize keys (once per station)
key_mgr = KeyManager("data/security")
info = key_mgr.generate_keys("MY-STATION-ID")
print(f"Fingerprint: {info['fingerprint']}")

# Add trusted station
key_mgr.add_trusted_station(
    station_id="OTHER-STATION",
    signing_public_key="...",
    encrypt_public_key="...",
)

# Export data
builder = SecureEnvelopeBuilder(key_mgr, "MY-STATION-ID")
envelope = builder.build_envelope(
    payload={"items": [...]},
    recipient_id="OTHER-STATION",
    data_type="INVENTORY_TRANSFER",
)
builder.envelope_to_file(envelope, "transfer.xirs")

# Import data (on receiving station)
verifier = EnvelopeVerifier(key_mgr, "OTHER-STATION")
payload, info = verifier.verify_file("transfer.xirs")
print(f"Received: {payload.data}")
```

## 10. Testing

Run the integration test:

```bash
python -m services.security.test_crypto
```

Expected output:
```
✓ ALL TESTS PASSED!
✅ All security tests passed. System is ready.
```

---

**Document Version:** 2.0
**Last Updated:** 2024-12-18
**Authors:** Claude Code + Human Review
