"""Shared password strength policy.

Applied to every field where a user chooses a password (registration, password
reset, change-password, invitation accept) so the rule lives in one place.
"""

import re
from typing import Annotated

from pydantic import AfterValidator

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 72  # bcrypt/argon2 input cap


def validate_password_strength(value: str) -> str:
    if len(value) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters"
        )
    if len(value) > MAX_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must be at most {MAX_PASSWORD_LENGTH} characters"
        )
    if not re.search(r"[A-Za-z]", value):
        raise ValueError("Password must contain at least one letter")
    if not re.search(r"\d", value):
        raise ValueError("Password must contain at least one number")
    return value


# Reusable field type: enforces the policy wherever a password is set.
StrongPassword = Annotated[str, AfterValidator(validate_password_strength)]
