"""
xIRS Secure Data Exchange Protocol (XSDEP) v2.0
Security module for authenticated encryption and digital signatures.

Target System: MIRS / CIRS / HIRS
Security Model: Authenticated Encryption + Digital Signatures + Replay Protection
Library: PyNaCl (libsodium binding)
"""

from .crypto_engine import KeyManager, SecureEnvelopeBuilder
from .envelope_verifier import EnvelopeVerifier
from .models import SecureEnvelope, EnvelopeHeader

__all__ = [
    'KeyManager',
    'SecureEnvelopeBuilder',
    'EnvelopeVerifier',
    'SecureEnvelope',
    'EnvelopeHeader',
]
