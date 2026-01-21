"""Tests for encryption utilities."""

import pytest

from ha_boss.core.encryption import (
    EncryptionError,
    TokenEncryption,
    decrypt_token,
    encrypt_token,
    get_encryption,
    mask_token,
)


@pytest.fixture
def encryption(tmp_path):
    """Create encryption instance with temp key file."""
    key_path = tmp_path / ".encryption_key"
    return TokenEncryption(key_path)


class TestTokenEncryption:
    """Tests for TokenEncryption class."""

    def test_encrypt_decrypt_roundtrip(self, encryption):
        """Test that encrypt/decrypt roundtrip preserves data."""
        original = "my_secret_token_12345"
        encrypted = encryption.encrypt(original)
        decrypted = encryption.decrypt(encrypted)
        assert decrypted == original

    def test_encrypted_differs_from_original(self, encryption):
        """Test that encrypted data differs from original."""
        original = "my_secret_token"
        encrypted = encryption.encrypt(original)
        assert encrypted != original

    def test_encrypt_empty_string_raises(self, encryption):
        """Test that encrypting empty string raises error."""
        with pytest.raises(EncryptionError, match="Cannot encrypt empty string"):
            encryption.encrypt("")

    def test_decrypt_empty_string_raises(self, encryption):
        """Test that decrypting empty string raises error."""
        with pytest.raises(EncryptionError, match="Cannot decrypt empty string"):
            encryption.decrypt("")

    def test_decrypt_invalid_token_raises(self, encryption):
        """Test that decrypting invalid token raises error."""
        with pytest.raises(EncryptionError):
            encryption.decrypt("not_a_valid_encrypted_token")

    def test_key_persists_between_instances(self, tmp_path):
        """Test that key persists and can decrypt across instances."""
        key_path = tmp_path / ".encryption_key"

        # First instance - encrypt
        enc1 = TokenEncryption(key_path)
        original = "test_token"
        encrypted = enc1.encrypt(original)

        # Second instance - decrypt
        enc2 = TokenEncryption(key_path)
        decrypted = enc2.decrypt(encrypted)
        assert decrypted == original

    def test_key_file_created(self, tmp_path):
        """Test that key file is created on first use."""
        key_path = tmp_path / ".encryption_key"
        assert not key_path.exists()

        encryption = TokenEncryption(key_path)
        encryption.encrypt("test")

        assert key_path.exists()

    def test_rotate_key_invalidates_old_encrypted_data(self, tmp_path):
        """Test that rotating key invalidates previously encrypted data."""
        key_path = tmp_path / ".encryption_key"

        enc = TokenEncryption(key_path)
        encrypted = enc.encrypt("test_token")

        # Rotate key
        enc.rotate_key()

        # Old encrypted data should fail to decrypt
        with pytest.raises(EncryptionError):
            enc.decrypt(encrypted)


class TestMaskToken:
    """Tests for mask_token function."""

    def test_mask_long_token(self):
        """Test masking a long token."""
        token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"
        masked = mask_token(token)
        assert masked.startswith("eyJ")
        assert masked.endswith("In0")
        assert "..." in masked

    def test_mask_short_token(self):
        """Test masking a short token returns asterisks."""
        token = "abc"
        masked = mask_token(token)
        assert masked == "***"

    def test_mask_empty_token(self):
        """Test masking empty string returns empty string."""
        assert mask_token("") == ""

    def test_mask_custom_visible_chars(self):
        """Test custom number of visible characters."""
        token = "1234567890"
        masked = mask_token(token, visible_chars=2)
        assert masked == "123...90"


class TestModuleFunctions:
    """Tests for module-level convenience functions."""

    def test_get_encryption_returns_singleton(self, tmp_path, monkeypatch):
        """Test that get_encryption returns same instance."""
        # Reset the singleton
        import ha_boss.core.encryption as enc_module

        monkeypatch.setattr(enc_module, "_encryption", None)
        monkeypatch.setattr(enc_module, "DEFAULT_KEY_PATH", tmp_path / ".key")

        enc1 = get_encryption()
        enc2 = get_encryption()
        assert enc1 is enc2

    def test_encrypt_decrypt_functions(self, tmp_path, monkeypatch):
        """Test module-level encrypt/decrypt functions."""
        import ha_boss.core.encryption as enc_module

        monkeypatch.setattr(enc_module, "_encryption", None)
        monkeypatch.setattr(enc_module, "DEFAULT_KEY_PATH", tmp_path / ".key")

        original = "test_token"
        encrypted = encrypt_token(original)
        decrypted = decrypt_token(encrypted)
        assert decrypted == original
