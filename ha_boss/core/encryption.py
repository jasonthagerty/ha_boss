"""Encryption utilities for secure token storage.

Uses Fernet symmetric encryption with auto-generated keys.
Key is stored in data/.encryption_key with restricted permissions.
"""

import base64
import logging
import os
import stat
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# Default key file location
DEFAULT_KEY_PATH = Path("/data/.encryption_key")


class EncryptionError(Exception):
    """Raised when encryption/decryption fails."""

    pass


class TokenEncryption:
    """Handles encryption and decryption of sensitive tokens.

    Uses Fernet symmetric encryption with a key stored on disk.
    Key file permissions are restricted to owner read/write only.
    """

    def __init__(self, key_path: Path | str | None = None) -> None:
        """Initialize encryption with key from file or generate new key.

        Args:
            key_path: Path to encryption key file. If None, uses default location.
        """
        self.key_path = Path(key_path) if key_path else DEFAULT_KEY_PATH
        self._fernet: Fernet | None = None

    def _ensure_key(self) -> bytes:
        """Ensure encryption key exists, creating if necessary.

        Returns:
            Encryption key bytes

        Raises:
            EncryptionError: If key cannot be read or created
        """
        try:
            if self.key_path.exists():
                # Read existing key
                key: bytes = self.key_path.read_bytes().strip()
                if len(key) == 0:
                    raise EncryptionError("Encryption key file is empty")
                # Validate key format
                try:
                    Fernet(key)
                except Exception as e:
                    raise EncryptionError(f"Invalid encryption key: {e}") from e
                return key
            else:
                # Generate new key
                key = Fernet.generate_key()

                # Create parent directory if needed
                self.key_path.parent.mkdir(parents=True, exist_ok=True)

                # Write key with restricted permissions
                self.key_path.write_bytes(key)

                # Restrict permissions to owner only (chmod 600)
                try:
                    os.chmod(self.key_path, stat.S_IRUSR | stat.S_IWUSR)
                except OSError as e:
                    logger.warning(f"Could not set permissions on key file: {e}")

                logger.info(f"Generated new encryption key at {self.key_path}")
                return key

        except EncryptionError:
            raise
        except Exception as e:
            raise EncryptionError(f"Failed to initialize encryption key: {e}") from e

    @property
    def fernet(self) -> Fernet:
        """Get Fernet instance, initializing key if needed."""
        if self._fernet is None:
            key = self._ensure_key()
            self._fernet = Fernet(key)
        return self._fernet

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a plaintext string.

        Args:
            plaintext: String to encrypt

        Returns:
            Base64-encoded encrypted string

        Raises:
            EncryptionError: If encryption fails
        """
        if not plaintext:
            raise EncryptionError("Cannot encrypt empty string")

        try:
            encrypted_bytes = self.fernet.encrypt(plaintext.encode("utf-8"))
            return base64.urlsafe_b64encode(encrypted_bytes).decode("ascii")
        except Exception as e:
            raise EncryptionError(f"Encryption failed: {e}") from e

    def decrypt(self, encrypted: str) -> str:
        """Decrypt an encrypted string.

        Args:
            encrypted: Base64-encoded encrypted string

        Returns:
            Decrypted plaintext string

        Raises:
            EncryptionError: If decryption fails (wrong key, corrupted data, etc.)
        """
        if not encrypted:
            raise EncryptionError("Cannot decrypt empty string")

        try:
            encrypted_bytes = base64.urlsafe_b64decode(encrypted.encode("ascii"))
            decrypted_bytes: bytes = self.fernet.decrypt(encrypted_bytes)
            return decrypted_bytes.decode("utf-8")
        except InvalidToken as e:
            raise EncryptionError("Decryption failed: invalid token or wrong key") from e
        except Exception as e:
            raise EncryptionError(f"Decryption failed: {e}") from e

    def rotate_key(self, new_key_path: Path | str | None = None) -> None:
        """Generate a new encryption key (does NOT re-encrypt existing data).

        Warning: After rotating the key, existing encrypted data will become
        unreadable. Call this only after re-encrypting all stored tokens.

        Args:
            new_key_path: Optional new path for the key file
        """
        if new_key_path:
            self.key_path = Path(new_key_path)

        # Force regeneration of key
        if self.key_path.exists():
            self.key_path.unlink()

        self._fernet = None
        self._ensure_key()
        logger.warning("Encryption key rotated - existing encrypted data is now invalid")


def mask_token(token: str, visible_chars: int = 4) -> str:
    """Mask a token for safe display.

    Args:
        token: Token to mask
        visible_chars: Number of characters to show at end

    Returns:
        Masked token like 'eyJ...xxxx'
    """
    if not token:
        return ""

    if len(token) <= visible_chars + 3:
        return "*" * len(token)

    return f"{token[:3]}...{token[-visible_chars:]}"


# Module-level singleton for convenience
_encryption: TokenEncryption | None = None


def get_encryption(key_path: Path | str | None = None) -> TokenEncryption:
    """Get the singleton TokenEncryption instance.

    Args:
        key_path: Optional path to encryption key (only used on first call)

    Returns:
        TokenEncryption instance
    """
    global _encryption
    if _encryption is None:
        _encryption = TokenEncryption(key_path)
    return _encryption


def encrypt_token(token: str) -> str:
    """Encrypt a token using the singleton encryption instance.

    Args:
        token: Token to encrypt

    Returns:
        Encrypted token string
    """
    return get_encryption().encrypt(token)


def decrypt_token(encrypted: str) -> str:
    """Decrypt a token using the singleton encryption instance.

    Args:
        encrypted: Encrypted token string

    Returns:
        Decrypted token
    """
    return get_encryption().decrypt(encrypted)
