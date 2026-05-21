# ============================================================================
# Field-level encryption for payroll PII (employee bank routing / account #s).
#
# Ciphertext is versioned with a "v{N}:" prefix so the active key can be
# rotated without a destructive re-encrypt:
#
#   PAYROLL_ENCRYPTION_SECRET       — current key, used to encrypt + try first
#                                     on decrypt
#   PAYROLL_ENCRYPTION_SECRET_PREV  — optional, last rotated-out key, used
#                                     only on decrypt
#
# Rotation procedure:
#   1. Move the live secret into PAYROLL_ENCRYPTION_SECRET_PREV.
#   2. Set the new secret as PAYROLL_ENCRYPTION_SECRET.
#   3. Bounce the app — new writes go out under the new key; old reads
#      transparently fall through to the previous key.
#   4. Run `python -m app.services.encryption rewrap` (offline) to re-encrypt
#      every stored ciphertext under the new key.
#   5. Drop PAYROLL_ENCRYPTION_SECRET_PREV.
# ============================================================================

import base64
import logging
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.config import PAYROLL_ENCRYPTION_SECRET

logger = logging.getLogger(__name__)

# Static salt — fine here because the secret itself is the protected material;
# rotating the secret rotates the derived key.
_SALT = b"slowbooks-payroll-v1"

# Version 1: current scheme. Bump if we ever change algorithm or salt.
_CURRENT_VERSION = 1
_VERSION_PREFIX = f"v{_CURRENT_VERSION}:"


def _derive_fernet(secret: str) -> Fernet:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        iterations=480000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(secret.encode("utf-8")))
    return Fernet(key)


def _active_fernets() -> list[Fernet]:
    """Build the decrypt-key chain: current first, then previous (if set)."""
    keys = [_derive_fernet(PAYROLL_ENCRYPTION_SECRET)]
    prev = os.environ.get("PAYROLL_ENCRYPTION_SECRET_PREV", "").strip()
    if prev and prev != PAYROLL_ENCRYPTION_SECRET:
        keys.append(_derive_fernet(prev))
    return keys


_fernets = _active_fernets()


def encrypt(plaintext: str | None) -> str | None:
    """Encrypt a string for storage. Returns None for empty input."""
    if plaintext is None or plaintext == "":
        return None
    token = _fernets[0].encrypt(plaintext.encode("utf-8")).decode("ascii")
    return _VERSION_PREFIX + token


def decrypt(token: str | None) -> str | None:
    """Decrypt a stored value. Tries the current key first, then any
    rotated-out previous key. Returns None for empty or undecryptable input."""
    if not token:
        return None

    raw = token[len(_VERSION_PREFIX) :] if token.startswith(_VERSION_PREFIX) else token

    for fernet in _fernets:
        try:
            return fernet.decrypt(raw.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError):
            continue

    logger.error("Failed to decrypt a stored secret with any configured key")
    return None
