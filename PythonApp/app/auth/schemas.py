from datetime import datetime
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
)

class AuthenticationLoginResponse(
    BaseModel
):
    id: UUID
    email: EmailStr
    username: str
    is_active: bool
    is_email_verified: bool
    created_at: datetime
    updated_at: datetime
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int

    model_config = ConfigDict(
        from_attributes=True,
    )

class AuthenticationRegisterRequest(BaseModel):
    username: str = Field(
        min_length=3,
        max_length=50,
    )
    
    email: EmailStr

    password: str = Field(
        min_length=8,
        max_length=128,
    )

class AuthenticationRegisterResponse(BaseModel):
    user_id: UUID
    email: EmailStr
    verification_required: bool
    message: str
    retry_after_seconds: int = 60


class VerifyEmailRequest(BaseModel):
    email: EmailStr

    code: str = Field(
        min_length=6,
        max_length=6,
        pattern=r"^\d{6}$",
    )


class VerifyEmailResponse(BaseModel):
    verified: bool
    message: str

class ResendVerificationRequest(BaseModel):
    email: EmailStr


class ResendVerificationResponse(BaseModel):
    message: str
    retry_after_seconds: int = 60

class UserResponse(BaseModel):
    id: UUID
    username: str
    email: EmailStr
    is_email_verified: bool

    model_config = ConfigDict(
        from_attributes=True
    )

class AuthenticationUserResponse(BaseModel):
    id: UUID
    email: EmailStr
    username: str
    is_active: bool
    is_email_verified: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True
    )

class RefreshTokenRequest(
    BaseModel
):
    refresh_token: str


class TokenRefreshResponse(
    BaseModel
):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int