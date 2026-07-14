import base64
import hashlib
import hmac
import os

HASH_VERSION = "pbkdf2_sha256_v1"
DEFAULT_ITERATIONS = 600_000
SALT_BYTES = 16


def hash_password(password: str) -> str:
    salt = os.urandom(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        DEFAULT_ITERATIONS,
    )
    return ":".join(
        [
            HASH_VERSION,
            str(DEFAULT_ITERATIONS),
            encode_bytes(salt),
            encode_bytes(digest),
        ]
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        version, iterations_text, salt_text, digest_text = stored_hash.split(":", 3)
        if version != HASH_VERSION:
            return False
        iterations = int(iterations_text)
        salt = decode_bytes(salt_text)
        expected = decode_bytes(digest_text)
    except ValueError, TypeError:
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual, expected)


def encode_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def decode_bytes(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
