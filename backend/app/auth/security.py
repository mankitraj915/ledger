"""Password hashing (Argon2id) and access tokens (JWT, HS256)."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher

from app.config import Settings
from app.errors import Unauthorized


def build_password_hasher(settings: Settings) -> PasswordHasher:
    return PasswordHasher(
        time_cost=settings.password_hash_time_cost,
        memory_cost=settings.password_hash_memory_kib,
        parallelism=1,
    )


@dataclass(frozen=True)
class TokenCodec:
    secret: str
    ttl: timedelta
    algorithm: str = "HS256"

    def issue(self, user_id: int, now: datetime | None = None) -> str:
        issued_at = now or datetime.now(UTC)
        claims = {"sub": str(user_id), "iat": issued_at, "exp": issued_at + self.ttl}
        return jwt.encode(claims, self.secret, algorithm=self.algorithm)

    def decode(self, token: str) -> int:
        """Return the user id in a valid, unexpired token; raise Unauthorized otherwise."""
        try:
            # Pinning `algorithms` rejects "alg": "none" and algorithm-confusion tokens.
            claims = jwt.decode(
                token,
                self.secret,
                algorithms=[self.algorithm],
                options={"require": ["sub", "iat", "exp"]},
            )
            return int(claims["sub"])
        except jwt.ExpiredSignatureError as exc:
            raise Unauthorized("Token has expired") from exc
        except (jwt.InvalidTokenError, ValueError) as exc:
            raise Unauthorized("Invalid token") from exc
