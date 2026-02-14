"""Fernet-based field encryption for health data at rest.

Raw health data (vitals, lab results, etc.) is encrypted before writing
to SQLite. Computed signal values (0-1 floats) remain unencrypted for
indexed longitudinal queries.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


class EncryptionError(Exception):
    """Raised when encryption/decryption fails."""


class FieldEncryptor:
    """Encrypts and decrypts JSON-serializable data using Fernet symmetric encryption.

    Usage::

        encryptor = FieldEncryptor(key="...")
        encrypted = encryptor.encrypt({"heart_rate": 72})
        decrypted = encryptor.decrypt(encrypted)  # {"heart_rate": 72}
    """

    def __init__(self, key: str) -> None:
        """Initialize with a Fernet key.

        Args:
            key: A valid Fernet key string. Generate with:
                 ``Fernet.generate_key().decode()``

        Raises:
            EncryptionError: If the key is empty or invalid.
        """
        if not key or not key.strip():
            raise EncryptionError("Encryption key must not be empty")
        try:
            self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
        except (ValueError, Exception) as exc:
            raise EncryptionError(f"Invalid encryption key: {exc}") from exc

    def encrypt(self, data: Any) -> str:
        """Encrypt a JSON-serializable value to a Fernet token string.

        Args:
            data: Any JSON-serializable Python object.

        Returns:
            Base64-encoded Fernet token as a string.

        Raises:
            EncryptionError: If serialization or encryption fails.
        """
        if data is None:
            return ""
        try:
            plaintext = json.dumps(data, separators=(",", ":")).encode("utf-8")
            return self._fernet.encrypt(plaintext).decode("utf-8")
        except Exception as exc:
            raise EncryptionError(f"Encryption failed: {exc}") from exc

    def decrypt(self, token: str) -> Any:
        """Decrypt a Fernet token string back to a Python object.

        Args:
            token: Base64-encoded Fernet token.

        Returns:
            The original Python object.

        Raises:
            EncryptionError: If the token is invalid or decryption fails.
        """
        if not token:
            return None
        try:
            plaintext = self._fernet.decrypt(token.encode("utf-8"))
            return json.loads(plaintext)
        except InvalidToken as exc:
            raise EncryptionError("Decryption failed: invalid token or wrong key") from exc
        except Exception as exc:
            raise EncryptionError(f"Decryption failed: {exc}") from exc

    @staticmethod
    def generate_key() -> str:
        """Generate a new Fernet key.

        Returns:
            A URL-safe base64-encoded 32-byte key as a string.
        """
        return Fernet.generate_key().decode("utf-8")
