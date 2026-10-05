"""Field-level cryptography — spec section 11.

- AES-256-GCM envelope: ``key_version || nonce(96-bit) || ciphertext+tag``
  via the host's existing ``pycryptodomex`` (no new crypto dependency).
- AAD is an unambiguous length-prefixed encoding of ``"infinitemarkets"``,
  record id, table, column, and key version — a ciphertext transplanted to
  another record/field fails authentication (tested).
- Equality indexes: HMAC-SHA256 under ``INFINITEMARKETS_PRIVACY_KEY`` over
  length-prefixed ``purpose + merchant_id + normalized value`` — the
  section-11.3 purpose names are distinct so indexes never collide.
- Public tokens (section 11.4): 256-bit base64url; lookup stores
  SHA-256(token bytes) compared with ``hmac.compare_digest``; malformed or
  non-canonical encodings are rejected before lookup.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import struct
import unicodedata

from Cryptodome.Cipher import AES
from Cryptodome.Random import get_random_bytes

AAD_PREFIX = "infinitemarkets"
NONCE_LEN = 12  # 96-bit GCM nonce
VERSION_LEN = 4  # key-version field width in the envelope

#: Section 11.3 equality-index purposes — one HMAC domain each.
PURPOSE_BUYER_PUBKEY = "buyer-pubkey"
PURPOSE_BUYER_EMAIL = "buyer-email"
PURPOSE_ORDER_ID = "order-id"
PURPOSE_WALLET_ID = "wallet-id"
PURPOSE_SOURCE_WALLET_ID = "source-wallet-id"
PURPOSE_CLIENT_IP = "client-ip"
PURPOSE_EMAIL_RECIPIENT = "email-recipient"

TOKEN_BYTES = 32  # 256-bit public token
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")


class CryptoError(ValueError):
    """Authentication/decoding failure — never carries key material."""


def _len_prefixed(fields: list[bytes]) -> bytes:
    """Unambiguous concatenation: each field prefixed by u32 length."""
    out = bytearray()
    for f in fields:
        out += struct.pack(">I", len(f))
        out += f
    return bytes(out)


def aad_for(record_id: str, table: str, column: str, key_version: str) -> bytes:
    return _len_prefixed(
        [
            AAD_PREFIX.encode(),
            record_id.encode(),
            table.encode(),
            column.encode(),
            key_version.encode(),
        ]
    )


def encrypt(
    plaintext: bytes,
    key: bytes,
    *,
    record_id: str,
    table: str,
    column: str,
    key_version: str,
) -> bytes:
    """AES-256-GCM envelope: ``key_version || nonce || ciphertext+tag``."""
    version_bytes = key_version.encode()
    if len(version_bytes) > VERSION_LEN:
        raise CryptoError("key_version exceeds envelope width")
    version_bytes = version_bytes.ljust(VERSION_LEN, b"\x00")
    nonce = get_random_bytes(NONCE_LEN)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    cipher.update(aad_for(record_id, table, column, key_version))
    ciphertext, tag = cipher.encrypt_and_digest(plaintext)
    return version_bytes + nonce + ciphertext + tag


def decrypt(
    envelope: bytes,
    key: bytes,
    *,
    record_id: str,
    table: str,
    column: str,
    key_version: str,
) -> bytes:
    """Verify AAD + tag and decrypt; raises CryptoError on any failure."""
    version_bytes = key_version.encode().ljust(VERSION_LEN, b"\x00")
    if len(envelope) < VERSION_LEN + NONCE_LEN + 16:
        raise CryptoError("envelope too short")
    if envelope[:VERSION_LEN] != version_bytes:
        raise CryptoError("key_version mismatch")
    nonce = envelope[VERSION_LEN : VERSION_LEN + NONCE_LEN]
    body = envelope[VERSION_LEN + NONCE_LEN :]
    ciphertext, tag = body[:-16], body[-16:]
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    cipher.update(aad_for(record_id, table, column, key_version))
    try:
        return cipher.decrypt_and_verify(ciphertext, tag)
    except ValueError as exc:
        raise CryptoError("envelope authentication failed") from exc


def envelope_version(envelope: bytes) -> str:
    """Read the key-version field (for rotation scans)."""
    return envelope[:VERSION_LEN].rstrip(b"\x00").decode()


def hmac_index(
    privacy_key: bytes,
    purpose: str,
    merchant_id: str,
    normalized_value: str,
) -> str:
    """Purpose-separated HMAC-SHA256 equality index (hex digest)."""
    msg = _len_prefixed(
        [purpose.encode(), merchant_id.encode(), normalized_value.encode()]
    )
    return hmac.new(privacy_key, msg, hashlib.sha256).hexdigest()


def normalize(value: str) -> str:
    """Canonical form for equality indexes: NFC + strip + lowercase."""
    return unicodedata.normalize("NFC", value).strip().lower()


# --- public tokens (section 11.4) --------------------------------------------


def generate_public_token() -> str:
    """256 random bits, base64url-encoded (no padding)."""
    return base64.urlsafe_b64encode(get_random_bytes(TOKEN_BYTES)).rstrip(b"=").decode()


def token_lookup_hash(token: str) -> bytes:
    """SHA-256 over the decoded token bytes; rejects malformed/non-canonical
    encodings BEFORE lookup (strict decode + re-encode comparison)."""
    if not _TOKEN_RE.match(token):
        raise CryptoError("malformed public token")
    raw = base64.urlsafe_b64decode(token + "=")
    if len(raw) != TOKEN_BYTES:
        raise CryptoError("malformed public token")
    if base64.urlsafe_b64encode(raw).rstrip(b"=").decode() != token:
        raise CryptoError("non-canonical public token encoding")
    return hashlib.sha256(raw).digest()


def tokens_equal(a: bytes, b: bytes) -> bool:
    return hmac.compare_digest(a, b)
