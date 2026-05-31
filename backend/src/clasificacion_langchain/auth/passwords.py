from __future__ import annotations

from passlib.context import CryptContext


# NOTE:
# bcrypt + passlib has compatibility issues in some Python/Windows environments
# (notably with newer bcrypt wheels). We use pbkdf2_sha256 as an adaptive,
# dependency-light baseline for this project foundation phase.
_PASSWORD_CONTEXT = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(raw_password: str) -> str:
    return _PASSWORD_CONTEXT.hash(raw_password)


def verify_password(raw_password: str, password_hash: str) -> bool:
    return _PASSWORD_CONTEXT.verify(raw_password, password_hash)
