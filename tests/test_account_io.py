from uma_api.account_io import encrypt_bundle, decrypt_bundle, BadPassphrase
import pytest

def test_roundtrip():
    payload = {"acc1": {"game": {"viewer_id": 1, "auth_key": "k"},
                        "steam": {"refresh_token": "t", "steam_id": "s"}}}
    blob = encrypt_bundle(payload, "hunter2")
    assert isinstance(blob, (bytes, bytearray))
    out = decrypt_bundle(blob, "hunter2")
    assert out == payload

def test_wrong_passphrase_raises():
    blob = encrypt_bundle({"a": {"game": {}, "steam": {}}}, "right")
    with pytest.raises(BadPassphrase):
        decrypt_bundle(blob, "wrong")

def test_tampered_ciphertext_raises():
    """Bit-flip in ciphertext must fail GCM tag verification."""
    blob = encrypt_bundle({"x": {"game": {"k": "v"}, "steam": None}}, "pass")
    # Flip the last byte of the ciphertext (past MAGIC+salt+nonce+tag)
    ba = bytearray(blob)
    ba[-1] ^= 0xFF
    with pytest.raises(BadPassphrase):
        decrypt_bundle(bytes(ba), "pass")

def test_truncated_blob_raises():
    """A blob too short to hold salt+nonce+tag must raise BadPassphrase, not a raw ValueError."""
    with pytest.raises(BadPassphrase):
        decrypt_bundle(b"UMAACCT1", "pass")  # MAGIC only, no header
