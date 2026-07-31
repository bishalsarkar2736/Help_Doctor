"""users.mfa_secret must not be readable from the database itself.

A TOTP secret is a symmetric seed, not a password: whoever holds it can mint
valid codes forever. In plaintext, one database read — a leaked dump, a stolen
backup, an over-broad support query — silently defeats every second factor in
the system, and nothing in the audit trail shows it happened.

The load-bearing test is test_ciphertext_is_what_reaches_the_database. Testing
only the round trip would pass just as happily with no encryption at all.
"""

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, text
from sqlalchemy.orm.attributes import flag_modified

from app.models.user import User, UserRole
from app.security.field_encryption import (
    EncryptedSecret,
    get_fernet,
    reset_fernet,
)
from app.security.jwt import hash_password

SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"  # 32-char base32, a real TOTP seed


@pytest.fixture
def fernet_reset():
    reset_fernet()
    yield
    reset_fernet()


async def _make_user(db, email: str, secret: str | None = SECRET) -> User:
    user = User(
        email=email,
        hashed_password=hash_password("Sup3rSecret!pw"),
        role=UserRole.ADMIN,
        is_active=True,
        mfa_secret=secret,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@pytest.mark.asyncio
async def test_ciphertext_is_what_reaches_the_database(db, fernet_reset):
    """Read the raw column, bypassing the ORM. This is the whole point."""
    user = await _make_user(db, "enc1@example.com")

    raw = await db.scalar(
        text("SELECT mfa_secret FROM users WHERE id = :i").bindparams(i=user.id)
    )

    assert raw is not None
    assert raw != SECRET, "the TOTP seed is sitting in the database in plaintext"
    assert SECRET not in raw
    assert raw.startswith("gAAAAA"), "value is not a Fernet token"


@pytest.mark.asyncio
async def test_round_trips_through_the_orm(db, fernet_reset):
    user = await _make_user(db, "enc2@example.com")
    # Capture the id BEFORE expiring: touching an expired attribute triggers a
    # lazy refresh, which raises MissingGreenlet under async SQLAlchemy.
    uid = user.id

    db.expire_all()
    reloaded = await db.scalar(select(User).where(User.id == uid))

    assert reloaded.mfa_secret == SECRET


@pytest.mark.asyncio
async def test_none_stays_none(db, fernet_reset):
    user = await _make_user(db, "enc3@example.com", secret=None)

    raw = await db.scalar(
        text("SELECT mfa_secret FROM users WHERE id = :i").bindparams(i=user.id)
    )
    assert raw is None
    assert user.mfa_secret is None


@pytest.mark.asyncio
async def test_ciphertext_differs_between_rows_with_the_same_secret(
    db, fernet_reset
):
    """Fernet includes a random IV, so identical seeds must not look identical.

    Otherwise an attacker with the dump could tell which accounts share a
    secret, and the column would leak information even while encrypted.
    """
    a = await _make_user(db, "enc4@example.com")
    b = await _make_user(db, "enc5@example.com")

    raw_a = await db.scalar(
        text("SELECT mfa_secret FROM users WHERE id = :i").bindparams(i=a.id)
    )
    raw_b = await db.scalar(
        text("SELECT mfa_secret FROM users WHERE id = :i").bindparams(i=b.id)
    )

    assert raw_a != raw_b


@pytest.mark.asyncio
async def test_ciphertext_fits_the_column(db, fernet_reset):
    """VARCHAR(64) would have truncated it and destroyed the secret."""
    user = await _make_user(db, "enc6@example.com")

    raw = await db.scalar(
        text("SELECT mfa_secret FROM users WHERE id = :i").bindparams(i=user.id)
    )
    assert len(raw) <= 255
    assert len(raw) > 64, "test is not exercising the width increase"


@pytest.mark.asyncio
async def test_legacy_plaintext_is_still_readable(db, fernet_reset):
    """A value written before encryption must not lock the user out."""
    user = await _make_user(db, "enc7@example.com", secret=None)
    uid = user.id

    await db.execute(
        text("UPDATE users SET mfa_secret = :s WHERE id = :i").bindparams(
            s=SECRET, i=uid
        )
    )
    await db.commit()
    db.expire_all()

    reloaded = await db.scalar(select(User).where(User.id == uid))
    assert reloaded.mfa_secret == SECRET


@pytest.mark.asyncio
async def test_legacy_plaintext_is_re_encrypted_on_next_write(db, fernet_reset):
    user = await _make_user(db, "enc8@example.com", secret=None)
    uid = user.id

    await db.execute(
        text("UPDATE users SET mfa_secret = :s WHERE id = :i").bindparams(
            s=SECRET, i=uid
        )
    )
    await db.commit()
    db.expire_all()

    reloaded = await db.scalar(select(User).where(User.id == uid))
    # flag_modified, not a plain re-assignment: assigning an identical value
    # can be optimised away at flush time and no UPDATE would be emitted.
    reloaded.mfa_secret = reloaded.mfa_secret
    flag_modified(reloaded, "mfa_secret")
    await db.commit()

    raw = await db.scalar(
        text("SELECT mfa_secret FROM users WHERE id = :i").bindparams(i=uid)
    )
    assert raw.startswith("gAAAAA"), "plaintext survived a write"


def test_undecryptable_ciphertext_raises_rather_than_returning_garbage():
    """A wrong key must fail loudly.

    Returning the raw ciphertext would hand the caller a string that silently
    fails every TOTP check — the user sees "invalid code" forever with no clue
    that the key is the problem.
    """
    reset_fernet()
    try:
        foreign = Fernet(Fernet.generate_key()).encrypt(b"x").decode()
        with pytest.raises(ValueError, match="could not be decrypted"):
            EncryptedSecret(255).process_result_value(foreign, None)
    finally:
        reset_fernet()


def test_key_rotation_keeps_old_values_readable(monkeypatch):
    """Prepending a new key must not orphan everything encrypted with the old."""
    from app.config import get_settings
    import app.security.field_encryption as fe

    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()

    base = get_settings()

    reset_fernet()
    monkeypatch.setattr(
        fe, "get_settings", lambda: base.model_copy(
            update={"MFA_SECRET_ENCRYPTION_KEYS": old_key}
        ), raising=False
    )
    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: base.model_copy(
            update={"MFA_SECRET_ENCRYPTION_KEYS": old_key}
        ),
    )
    token = get_fernet().encrypt(SECRET.encode()).decode()

    # Rotate: new key first, old key retained for reads.
    reset_fernet()
    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: base.model_copy(
            update={"MFA_SECRET_ENCRYPTION_KEYS": f"{new_key},{old_key}"}
        ),
    )

    assert get_fernet().decrypt(token.encode()).decode() == SECRET
    reset_fernet()
