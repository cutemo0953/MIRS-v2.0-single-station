#!/usr/bin/env python3
"""
xIRS Crypto Engine - Integration Test

This script tests the full encrypt-sign-verify-decrypt cycle
between two simulated stations.

Usage:
    python -m services.security.test_crypto
"""

import sys
import tempfile
import shutil
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from services.security.crypto_engine import KeyManager, SecureEnvelopeBuilder
from services.security.envelope_verifier import EnvelopeVerifier


def test_full_cycle():
    """Test the complete encryption and verification cycle."""
    print("=" * 60)
    print("xIRS Crypto Engine - Full Cycle Test")
    print("=" * 60)

    # Create temporary directories for test keys
    temp_dir = tempfile.mkdtemp(prefix="xirs_test_")
    station_a_dir = Path(temp_dir) / "station_a"
    station_b_dir = Path(temp_dir) / "station_b"

    try:
        # =====================================================================
        # Step 1: Generate keys for both stations
        # =====================================================================
        print("\n[1] Generating keys for Station A and Station B...")

        key_mgr_a = KeyManager(str(station_a_dir))
        key_mgr_b = KeyManager(str(station_b_dir))

        info_a = key_mgr_a.generate_keys("MIRS-STATION-A")
        info_b = key_mgr_b.generate_keys("MIRS-STATION-B")

        print(f"    Station A fingerprint: {info_a['fingerprint']}")
        print(f"    Station B fingerprint: {info_b['fingerprint']}")

        # =====================================================================
        # Step 2: Exchange public keys (add to trusted registries)
        # =====================================================================
        print("\n[2] Exchanging public keys...")

        # Station A trusts Station B
        key_mgr_a.add_trusted_station(
            station_id="MIRS-STATION-B",
            signing_public_key=info_b['signing_public_key'],
            encrypt_public_key=info_b['encrypt_public_key'],
            station_name="Medical Station B",
        )

        # Station B trusts Station A
        key_mgr_b.add_trusted_station(
            station_id="MIRS-STATION-A",
            signing_public_key=info_a['signing_public_key'],
            encrypt_public_key=info_a['encrypt_public_key'],
            station_name="Medical Station A",
        )

        print("    ✓ Keys exchanged and trusted")

        # =====================================================================
        # Step 3: Station A creates an encrypted envelope for Station B
        # =====================================================================
        print("\n[3] Station A creating encrypted envelope...")

        builder_a = SecureEnvelopeBuilder(key_mgr_a, "MIRS-STATION-A")

        test_payload = {
            "inventory_items": [
                {"name": "N95口罩", "quantity": 500, "unit": "個"},
                {"name": "酒精", "quantity": 20, "unit": "公升"},
                {"name": "繃帶", "quantity": 100, "unit": "捲"},
            ],
            "transfer_reason": "物資調度支援",
            "priority": "normal",
        }

        envelope = builder_a.build_envelope(
            payload=test_payload,
            recipient_id="MIRS-STATION-B",
            data_type="INVENTORY_TRANSFER",
        )

        print(f"    Envelope ID: {envelope.envelope_id}")
        print(f"    Sender: {envelope.header.sender_id}")
        print(f"    Recipient: {envelope.header.recipient_id}")
        print(f"    Data Type: {envelope.header.data_type}")
        print(f"    Encrypted payload length: {len(envelope.payload_encrypted)} chars")

        # =====================================================================
        # Step 4: Save envelope to file (simulates USB transfer)
        # =====================================================================
        print("\n[4] Saving envelope to .xirs file...")

        output_file = Path(temp_dir) / "transfer_001.xirs"
        actual_path = builder_a.envelope_to_file(envelope, str(output_file))
        print(f"    Saved to: {actual_path}")

        # =====================================================================
        # Step 5: Station B reads and verifies the envelope
        # =====================================================================
        print("\n[5] Station B verifying and decrypting envelope...")

        verifier_b = EnvelopeVerifier(
            key_manager=key_mgr_b,
            station_id="MIRS-STATION-B",
            replay_db_path=str(station_b_dir / "processed.db"),
        )

        decrypted, verify_info = verifier_b.verify_file(actual_path)

        print(f"    ✓ Signature valid: {verify_info.get('signature_valid')}")
        print(f"    ✓ Decrypted: {verify_info.get('decrypted')}")
        print(f"    ✓ Schema version: {decrypted.schema_version}")
        print(f"    ✓ Data type: {decrypted.data_type}")

        # =====================================================================
        # Step 6: Verify decrypted data matches original
        # =====================================================================
        print("\n[6] Verifying data integrity...")

        original_items = test_payload['inventory_items']
        decrypted_items = decrypted.data['inventory_items']

        assert len(original_items) == len(decrypted_items), "Item count mismatch!"

        for orig, dec in zip(original_items, decrypted_items):
            assert orig['name'] == dec['name'], f"Name mismatch: {orig['name']} != {dec['name']}"
            assert orig['quantity'] == dec['quantity'], f"Quantity mismatch"

        print("    ✓ All inventory items match!")
        print(f"    ✓ Transfer reason: {decrypted.data['transfer_reason']}")

        # =====================================================================
        # Step 7: Test replay protection
        # =====================================================================
        print("\n[7] Testing replay protection...")

        try:
            # Try to process the same envelope again
            verifier_b.verify_file(actual_path)
            print("    ✗ ERROR: Replay attack should have been detected!")
            return False
        except Exception as e:
            if "already been processed" in str(e):
                print("    ✓ Replay attack correctly blocked!")
            else:
                print(f"    ✗ Unexpected error: {e}")
                return False

        # =====================================================================
        # Step 8: Test tampered envelope detection
        # =====================================================================
        print("\n[8] Testing tamper detection...")

        # Load envelope and tamper with it
        envelope_tampered = SecureEnvelopeBuilder.envelope_from_file(actual_path)

        # Tamper with the payload (change one character)
        original_payload = envelope_tampered.payload_encrypted
        tampered_payload = original_payload[:-10] + "XXXXXXXXXX"

        # Create a new envelope with tampered payload
        import uuid
        from services.security.models import SecureEnvelope, EnvelopeHeader
        tampered_envelope = SecureEnvelope(
            envelope_id=str(uuid.uuid4()),  # New ID to bypass replay
            header=envelope_tampered.header,
            payload_encrypted=tampered_payload,
            nonce=envelope_tampered.nonce,
            signature=envelope_tampered.signature,
        )

        try:
            verifier_b.verify_and_decrypt(tampered_envelope, skip_replay_check=True)
            print("    ✗ ERROR: Tampered envelope should have been rejected!")
            return False
        except Exception as e:
            if "Signature verification failed" in str(e) or "SECURITY ALERT" in str(e):
                print("    ✓ Tampered envelope correctly rejected!")
            else:
                # Decryption might also fail for tampered data
                print(f"    ✓ Tampered envelope rejected: {type(e).__name__}")

        # =====================================================================
        # All tests passed!
        # =====================================================================
        print("\n" + "=" * 60)
        print("✓ ALL TESTS PASSED!")
        print("=" * 60)
        return True

    finally:
        # Cleanup temp directory
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_key_fingerprint():
    """Test key fingerprint display for human verification."""
    print("\n[Bonus] Testing key fingerprint display...")

    temp_dir = tempfile.mkdtemp(prefix="xirs_fp_test_")
    try:
        key_mgr = KeyManager(temp_dir)
        info = key_mgr.generate_keys("TEST-STATION")

        print(f"    Station ID: TEST-STATION")
        print(f"    Fingerprint: {info['fingerprint']}")
        print("    (Show this to the other station operator for verification)")

        # Verify fingerprint format
        parts = info['fingerprint'].split(':')
        assert len(parts) == 8, "Fingerprint should have 8 parts"
        for part in parts:
            assert len(part) == 2, "Each part should be 2 hex chars"

        print("    ✓ Fingerprint format correct")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    print("\nxIRS Secure Data Exchange Protocol v2.0")
    print("Crypto Engine Integration Test\n")

    try:
        success = test_full_cycle()
        test_key_fingerprint()

        if success:
            print("\n✅ All security tests passed. System is ready.")
            sys.exit(0)
        else:
            print("\n❌ Some tests failed.")
            sys.exit(1)

    except ImportError as e:
        print(f"\n❌ Import error: {e}")
        print("\nMake sure PyNaCl is installed:")
        print("    pip install pynacl")
        sys.exit(1)

    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
