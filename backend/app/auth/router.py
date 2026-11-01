from fastapi import APIRouter, status

from app.auth import service
from app.auth.deps import CurrentUser, PasswordHasherDep, TokenCodecDep
from app.auth.models import User
from app.auth.schemas import LoginIn, RegisterIn, TokenOut, UserOut
from app.auth.security import TokenCodec
from app.db import SessionDep

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_for(user: User, codec: TokenCodec) -> TokenOut:
    return TokenOut(access_token=codec.issue(user.id), user=UserOut.model_validate(user))


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterIn, session: SessionDep, hasher: PasswordHasherDep, codec: TokenCodecDep
) -> TokenOut:
    return _token_for(service.register(session, hasher, payload), codec)


@router.post("/login")
def login(
    payload: LoginIn, session: SessionDep, hasher: PasswordHasherDep, codec: TokenCodecDep
) -> TokenOut:
    user = service.authenticate(session, hasher, payload.email, payload.password)
    return _token_for(user, codec)


@router.get("/me")
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)
