from typing import Annotated

from argon2 import PasswordHasher
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.models import User
from app.auth.security import TokenCodec
from app.db import SessionDep
from app.errors import Unauthorized

_bearer = HTTPBearer(auto_error=False)


def get_token_codec(request: Request) -> TokenCodec:
    codec: TokenCodec = request.app.state.token_codec
    return codec


def get_password_hasher(request: Request) -> PasswordHasher:
    hasher: PasswordHasher = request.app.state.password_hasher
    return hasher


TokenCodecDep = Annotated[TokenCodec, Depends(get_token_codec)]
PasswordHasherDep = Annotated[PasswordHasher, Depends(get_password_hasher)]


def get_current_user(
    session: SessionDep,
    codec: TokenCodecDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise Unauthorized("Missing bearer token")
    user = session.get(User, codec.decode(credentials.credentials))
    if user is None:
        raise Unauthorized("Invalid token")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
