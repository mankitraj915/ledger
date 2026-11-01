import logging
from functools import cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from psycopg.errors import UniqueViolation
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import User
from app.auth.schemas import RegisterIn
from app.db import transaction
from app.errors import Conflict, Unauthorized

logger = logging.getLogger(__name__)


class EmailTaken(Conflict):
    code = "email_taken"


class InvalidCredentials(Unauthorized):
    code = "invalid_credentials"

    def __init__(self) -> None:
        super().__init__("Invalid email or password")


def register(session: Session, hasher: PasswordHasher, payload: RegisterIn) -> User:
    user = User(email=payload.email, name=payload.name, password_hash=hasher.hash(payload.password))
    try:
        with transaction(session):
            session.add(user)
    except IntegrityError as exc:
        # The unique index is the source of truth; checking first would be a race.
        if isinstance(exc.orig, UniqueViolation):
            raise EmailTaken("An account with this email already exists") from exc
        raise
    logger.info("user.registered", extra={"user_id": user.id})
    return user


@cache
def _dummy_hash(hasher: PasswordHasher) -> str:
    return hasher.hash("dummy password, never matches")


def authenticate(session: Session, hasher: PasswordHasher, email: str, password: str) -> User:
    user = session.scalars(select(User).where(User.email == email)).one_or_none()
    if user is None:
        # Spend the same time as a real check so response timing does not reveal
        # which emails have accounts.
        _verify(hasher, _dummy_hash(hasher), password)
        raise InvalidCredentials()
    if not _verify(hasher, user.password_hash, password):
        raise InvalidCredentials()
    if hasher.check_needs_rehash(user.password_hash):
        with transaction(session):
            user.password_hash = hasher.hash(password)
    return user


def _verify(hasher: PasswordHasher, password_hash: str, password: str) -> bool:
    try:
        return hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False
