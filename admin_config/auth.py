"""Password hashing for the admin_config service. Uses stdlib
hashlib.pbkdf2_hmac instead of adding a passlib/bcrypt dependency — this
service isn't installed anywhere else in the codebase, and PBKDF2-SHA256 at
200k iterations is a reasonable, dependency-free choice for a single-operator
admin tool."""
import hashlib
import hmac
import secrets

_ALGO = "sha256"
_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(_ALGO, password.encode("utf-8"), bytes.fromhex(salt), _ITERATIONS)
    return f"{salt}:{digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest_hex = stored.split(":", 1)
    except ValueError:
        return False
    expected = hashlib.pbkdf2_hmac(_ALGO, password.encode("utf-8"), bytes.fromhex(salt), _ITERATIONS)
    return hmac.compare_digest(expected.hex(), digest_hex)
