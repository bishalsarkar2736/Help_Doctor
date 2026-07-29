import hashlib
import secrets
import hmac


def generate_secure_token(length: int = 32) -> str:
    """
    Generate a cryptographically secure URL-safe token.

    Default:
        32 bytes -> ~43 character string
    """
    return secrets.token_urlsafe(length)


def generate_otp(digits: int = 6) -> str:
    """
    Generate a cryptographically secure numeric one-time code.

    Zero-padded, so "004312" is a valid 6-digit code. NOTE: the keyspace is only
    10**digits, so a code is guessable by brute force — verification MUST be
    scoped to a single user AND attempt-limited (see verify_email_otp).
    """
    upper = 10**digits
    return str(secrets.randbelow(upper)).zfill(digits)


def hash_token(token: str) -> str:
    """
    Hash a token before storing it in the database.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_token_hash(token: str, token_hash: str) -> bool:
    """
    Verify a raw token against its stored hash.

    Uses constant-time comparison to prevent timing attacks.
    """
    computed_hash = hash_token(token)

    return hmac.compare_digest(
        computed_hash,
        token_hash,
    )