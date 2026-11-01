from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, StringConstraints

NormalisedEmail = Annotated[EmailStr, AfterValidator(str.lower)]
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class RegisterIn(BaseModel):
    email: NormalisedEmail
    name: DisplayName
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: NormalisedEmail
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - a token type, not a secret
    user: UserOut
