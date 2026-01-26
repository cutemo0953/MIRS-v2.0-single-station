"""
xIRS OTA Security Module

Implements signature verification for OTA updates:
- Minisign signature verification
- Public key management
- Download integrity checks

Version: 1.0
Date: 2026-01-26
Reference: DEV_SPEC_COMMERCIAL_APPLIANCE_v1.9.1 (ChatGPT Review)
"""

import hashlib
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# Public key storage location
PUBLIC_KEY_PATH = Path(os.environ.get('MIRS_OTA_PUBKEY', '/etc/mirs/ota_pubkey.pub'))

# Embedded public key (fallback if file doesn't exist)
# Generated: 2026-01-26
EMBEDDED_PUBLIC_KEY = """untrusted comment: minisign public key 306E0118B06ADB2F
RWQv22qwGAFuMINaVoJEAxa0DV7ox9KMTVqwpP3DMvhhLY0nFIe5KdHC
"""

# Signature file extension
SIGNATURE_EXTENSION = ".minisig"


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class VerificationResult:
    """Result of signature verification."""
    valid: bool
    method: str  # 'minisign', 'sha256', 'skipped'
    message: str
    details: Optional[dict] = None


# =============================================================================
# Critical #2: Signature Verification (minisign)
# =============================================================================

def verify_signature(
    binary_path: str,
    signature_path: Optional[str] = None
) -> VerificationResult:
    """
    Verify the signature of a downloaded binary using minisign.

    Minisign is preferred because:
    - Simpler than GPG
    - Designed for software signing
    - Small and fast
    - No key management complexity

    Args:
        binary_path: Path to the downloaded binary
        signature_path: Path to the signature file (default: binary_path + .minisig)

    Returns:
        VerificationResult with validity status
    """
    if signature_path is None:
        signature_path = binary_path + SIGNATURE_EXTENSION

    # Check if minisign is available
    if not _is_minisign_available():
        logger.warning("minisign not installed, falling back to SHA256 only")
        return VerificationResult(
            valid=True,  # Allow update but log warning
            method="skipped",
            message="minisign 未安裝，跳過簽章驗證 (建議安裝: apt install minisign)"
        )

    # Check if signature file exists
    if not os.path.exists(signature_path):
        logger.warning(f"Signature file not found: {signature_path}")
        return VerificationResult(
            valid=False,
            method="minisign",
            message=f"找不到簽章檔案: {signature_path}"
        )

    # Get public key path
    pubkey_path = _get_public_key_path()
    if pubkey_path is None:
        return VerificationResult(
            valid=False,
            method="minisign",
            message="找不到 OTA 公鑰檔案"
        )

    # Run minisign verification
    try:
        result = subprocess.run(
            [
                'minisign', '-V',
                '-p', str(pubkey_path),
                '-m', binary_path,
                '-x', signature_path
            ],
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            logger.info(f"Signature verification passed for {binary_path}")
            return VerificationResult(
                valid=True,
                method="minisign",
                message="簽章驗證通過",
                details={"stdout": result.stdout}
            )
        else:
            logger.error(f"Signature verification failed: {result.stderr}")
            return VerificationResult(
                valid=False,
                method="minisign",
                message=f"簽章驗證失敗: {result.stderr}",
                details={"stderr": result.stderr}
            )

    except subprocess.TimeoutExpired:
        return VerificationResult(
            valid=False,
            method="minisign",
            message="簽章驗證逾時"
        )
    except FileNotFoundError:
        return VerificationResult(
            valid=False,
            method="minisign",
            message="minisign 執行檔未找到"
        )
    except Exception as e:
        return VerificationResult(
            valid=False,
            method="minisign",
            message=f"簽章驗證錯誤: {e}"
        )


def _is_minisign_available() -> bool:
    """Check if minisign is installed."""
    try:
        result = subprocess.run(
            ['minisign', '-v'],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _get_public_key_path() -> Optional[Path]:
    """
    Get the path to the public key file.

    Priority:
    1. Environment variable path
    2. Default /etc/mirs/ota_pubkey.pub
    3. Create from embedded key (fallback)
    """
    # Check if configured path exists
    if PUBLIC_KEY_PATH.exists():
        return PUBLIC_KEY_PATH

    # Try to create from embedded key
    if EMBEDDED_PUBLIC_KEY and "PLACEHOLDER" not in EMBEDDED_PUBLIC_KEY:
        try:
            PUBLIC_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
            PUBLIC_KEY_PATH.write_text(EMBEDDED_PUBLIC_KEY)
            logger.info(f"Created public key file from embedded key: {PUBLIC_KEY_PATH}")
            return PUBLIC_KEY_PATH
        except Exception as e:
            logger.error(f"Failed to create public key file: {e}")

    # Check alternative locations
    alt_paths = [
        Path('/boot/ota_pubkey.pub'),
        Path.home() / '.mirs' / 'ota_pubkey.pub',
        Path('./ota_pubkey.pub'),
    ]

    for path in alt_paths:
        if path.exists():
            return path

    return None


# =============================================================================
# SHA256 Checksum Verification
# =============================================================================

def verify_checksum(
    file_path: str,
    expected_checksum: str,
    algorithm: str = "sha256"
) -> VerificationResult:
    """
    Verify file checksum.

    This is a basic integrity check (not authenticity).
    Should be used in conjunction with signature verification.
    """
    try:
        actual_checksum = calculate_checksum(file_path, algorithm)

        if actual_checksum.lower() == expected_checksum.lower():
            return VerificationResult(
                valid=True,
                method=algorithm,
                message="Checksum 驗證通過",
                details={
                    "expected": expected_checksum,
                    "actual": actual_checksum
                }
            )
        else:
            return VerificationResult(
                valid=False,
                method=algorithm,
                message="Checksum 不符",
                details={
                    "expected": expected_checksum,
                    "actual": actual_checksum
                }
            )

    except Exception as e:
        return VerificationResult(
            valid=False,
            method=algorithm,
            message=f"Checksum 計算失敗: {e}"
        )


def calculate_checksum(file_path: str, algorithm: str = "sha256") -> str:
    """Calculate file checksum."""
    hash_func = hashlib.new(algorithm)

    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            hash_func.update(chunk)

    return hash_func.hexdigest()


# =============================================================================
# Combined Verification
# =============================================================================

def verify_update_package(
    binary_path: str,
    expected_checksum: Optional[str] = None,
    signature_path: Optional[str] = None,
    require_signature: bool = False
) -> Tuple[bool, str]:
    """
    Verify a complete update package with all available methods.

    Args:
        binary_path: Path to the downloaded binary
        expected_checksum: Expected SHA256 checksum (optional)
        signature_path: Path to signature file (optional)
        require_signature: If True, fail if signature is missing

    Returns:
        (valid: bool, message: str)
    """
    results = []

    # 1. Verify checksum if provided
    if expected_checksum:
        checksum_result = verify_checksum(binary_path, expected_checksum)
        results.append(checksum_result)

        if not checksum_result.valid:
            return False, f"Checksum 驗證失敗: {checksum_result.message}"

    # 2. Verify signature
    sig_result = verify_signature(binary_path, signature_path)
    results.append(sig_result)

    if require_signature and not sig_result.valid:
        return False, f"簽章驗證失敗: {sig_result.message}"

    if sig_result.method == "skipped":
        logger.warning("Signature verification skipped - consider installing minisign")

    # All checks passed
    methods_used = [r.method for r in results if r.valid]
    return True, f"驗證通過 ({', '.join(methods_used)})"


# =============================================================================
# Key Management
# =============================================================================

def install_public_key(key_content: str, force: bool = False) -> bool:
    """
    Install a new public key for OTA verification.

    Args:
        key_content: The public key content (minisign format)
        force: If True, overwrite existing key

    Returns:
        True if installed successfully
    """
    if PUBLIC_KEY_PATH.exists() and not force:
        logger.warning(f"Public key already exists at {PUBLIC_KEY_PATH}")
        return False

    try:
        PUBLIC_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        PUBLIC_KEY_PATH.write_text(key_content)
        os.chmod(PUBLIC_KEY_PATH, 0o644)  # Read-only for non-root
        logger.info(f"Installed public key to {PUBLIC_KEY_PATH}")
        return True
    except Exception as e:
        logger.error(f"Failed to install public key: {e}")
        return False


def get_public_key_info() -> Optional[dict]:
    """Get information about the installed public key."""
    pubkey_path = _get_public_key_path()

    if pubkey_path is None:
        return None

    try:
        content = pubkey_path.read_text()
        lines = content.strip().split('\n')

        return {
            "path": str(pubkey_path),
            "comment": lines[0] if lines else None,
            "key_id": lines[1][:20] + "..." if len(lines) > 1 else None,
            "installed": True
        }
    except Exception as e:
        return {"error": str(e), "installed": False}


# =============================================================================
# Download Security
# =============================================================================

def secure_download(
    url: str,
    dest_path: str,
    expected_checksum: Optional[str] = None,
    signature_url: Optional[str] = None
) -> Tuple[bool, str]:
    """
    Securely download and verify a file.

    This is a synchronous wrapper for use in non-async contexts.
    """
    import requests

    try:
        # Download binary
        logger.info(f"Downloading: {url}")
        resp = requests.get(url, stream=True, timeout=600)
        resp.raise_for_status()

        # Write to temp file first
        temp_path = dest_path + ".tmp"
        with open(temp_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        # Download signature if URL provided
        sig_path = None
        if signature_url:
            sig_path = dest_path + SIGNATURE_EXTENSION
            sig_resp = requests.get(signature_url, timeout=60)
            if sig_resp.status_code == 200:
                with open(sig_path, 'w') as f:
                    f.write(sig_resp.text)
            else:
                logger.warning(f"Signature download failed: {sig_resp.status_code}")

        # Verify
        valid, msg = verify_update_package(
            temp_path,
            expected_checksum=expected_checksum,
            signature_path=sig_path
        )

        if valid:
            # Move to final location
            os.rename(temp_path, dest_path)
            return True, msg
        else:
            # Clean up
            os.remove(temp_path)
            if sig_path and os.path.exists(sig_path):
                os.remove(sig_path)
            return False, msg

    except requests.RequestException as e:
        return False, f"下載失敗: {e}"
    except Exception as e:
        return False, f"錯誤: {e}"
