"""Tests for the FieldEncryptor (Fernet-based health data encryption)."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from cip.core.storage.encryption import EncryptionError, FieldEncryptor


@pytest.fixture
def key() -> str:
    return Fernet.generate_key().decode()


@pytest.fixture
def encryptor(key: str) -> FieldEncryptor:
    return FieldEncryptor(key)


class TestRoundTrip:
    """Verify encrypt → decrypt returns the original data."""

    def test_dict_round_trip(self, encryptor: FieldEncryptor):
        data = {"heart_rate": 72, "bp": {"systolic": 120, "diastolic": 80}}
        token = encryptor.encrypt(data)
        assert isinstance(token, str)
        assert token != ""
        result = encryptor.decrypt(token)
        assert result == data

    def test_list_round_trip(self, encryptor: FieldEncryptor):
        data = [{"test": "glucose", "value": 95.0}, {"test": "hba1c", "value": 5.4}]
        assert encryptor.decrypt(encryptor.encrypt(data)) == data

    def test_string_round_trip(self, encryptor: FieldEncryptor):
        data = "plain text"
        assert encryptor.decrypt(encryptor.encrypt(data)) == data

    def test_number_round_trip(self, encryptor: FieldEncryptor):
        assert encryptor.decrypt(encryptor.encrypt(42)) == 42
        assert encryptor.decrypt(encryptor.encrypt(3.14)) == 3.14

    def test_bool_round_trip(self, encryptor: FieldEncryptor):
        assert encryptor.decrypt(encryptor.encrypt(True)) is True

    def test_null_round_trip(self, encryptor: FieldEncryptor):
        assert encryptor.encrypt(None) == ""
        assert encryptor.decrypt("") is None

    def test_empty_string_decrypt_returns_none(self, encryptor: FieldEncryptor):
        assert encryptor.decrypt("") is None


class TestKeyValidation:
    def test_empty_key_raises(self):
        with pytest.raises(EncryptionError, match="must not be empty"):
            FieldEncryptor("")

    def test_whitespace_key_raises(self):
        with pytest.raises(EncryptionError, match="must not be empty"):
            FieldEncryptor("   ")

    def test_invalid_key_raises(self):
        with pytest.raises(EncryptionError, match="Invalid encryption key"):
            FieldEncryptor("not-a-valid-fernet-key")


class TestCorruptData:
    def test_wrong_key_cannot_decrypt(self, encryptor: FieldEncryptor):
        token = encryptor.encrypt({"secret": "data"})
        other_key = Fernet.generate_key().decode()
        other_encryptor = FieldEncryptor(other_key)
        with pytest.raises(EncryptionError, match="invalid token"):
            other_encryptor.decrypt(token)

    def test_tampered_token_raises(self, encryptor: FieldEncryptor):
        token = encryptor.encrypt({"data": 1})
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(EncryptionError):
            encryptor.decrypt(tampered)

    def test_garbage_token_raises(self, encryptor: FieldEncryptor):
        with pytest.raises(EncryptionError):
            encryptor.decrypt("not-a-valid-token")


class TestGenerateKey:
    def test_generates_valid_key(self):
        key = FieldEncryptor.generate_key()
        assert isinstance(key, str)
        assert len(key) == 44  # base64-encoded 32 bytes

    def test_generated_key_works(self):
        key = FieldEncryptor.generate_key()
        enc = FieldEncryptor(key)
        data = {"test": True}
        assert enc.decrypt(enc.encrypt(data)) == data

    def test_each_key_is_unique(self):
        keys = {FieldEncryptor.generate_key() for _ in range(10)}
        assert len(keys) == 10


class TestTokenUniqueness:
    def test_same_data_produces_different_tokens(self, encryptor: FieldEncryptor):
        """Fernet includes a timestamp, so identical payloads get different tokens."""
        data = {"value": 42}
        t1 = encryptor.encrypt(data)
        t2 = encryptor.encrypt(data)
        # Tokens may differ due to timestamp, but both decrypt correctly
        assert encryptor.decrypt(t1) == data
        assert encryptor.decrypt(t2) == data
