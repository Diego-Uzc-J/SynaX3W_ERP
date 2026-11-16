"""Esquemas Pydantic v2 del módulo de Usuarios, Roles y Seguridad.

Derivados de ``specs/users_spec.md`` (secciones 4.2 y 5). Se aplican tres
principios transversales:

* **Sin asignación masiva**: todos los esquemas declaran
  ``ConfigDict(extra="forbid")``; un campo no autorizado (por ejemplo
  ``hashed_password``, ``role`` o ``failed_login_attempts``) produce 422.
* **Política de contraseñas**: ``StrongPassword`` reutiliza
  ``validate_password_strength`` de ``src.core.security`` (10–128 caracteres,
  mayúscula, minúscula, número y carácter especial).
* **Sin filtración de secretos**: ``UserResponse`` enumera explícitamente sus
  campos y nunca incluye ``hashed_password``; las credenciales de entrada usan
  ``SecretStr`` para evitar que aparezcan en ``repr`` o logs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from src.core.security import validate_password_strength
from src.modules.users.models import RoleEnum

__all__ = [
    "CaptchaResponse",
    "LoginRequest",
    "LoginResponse",
    "PasswordUpdate",
    "RefreshRequest",
    "RefreshResponse",
    "RoleResponse",
    "StrongPassword",
    "TokenResponse",
    "UserCreate",
    "UserResponse",
    "UserUpdate",
]


class UserSchema(BaseModel):
    """Base de los esquemas del módulo con rechazo de campos desconocidos."""

    model_config = ConfigDict(extra="forbid")


def _validate_strong_password(value: SecretStr) -> SecretStr:
    """Aplica la política de la sección 4.2 al valor envuelto por ``SecretStr``."""
    validate_password_strength(value.get_secret_value())
    return value


#: Contraseña válida según la política del ERP. Se usa en creación y
#: restablecimiento, nunca en el login (allí basta con verificar el hash).
StrongPassword = Annotated[SecretStr, AfterValidator(_validate_strong_password)]


# --------------------------------------------------------------------------- #
# Autenticación — /api/v1/users/auth
# --------------------------------------------------------------------------- #


class CaptchaResponse(UserSchema):
    """Desafío aritmético listo para que el cliente lo resuelva."""

    question: str = Field(
        description="Suma que debe resolver el usuario.",
        examples=["¿Cuánto es 7 + 12?"],
    )
    captcha_token: str = Field(
        description="Token firmado que debe reenviarse en el login.",
    )


class LoginRequest(UserSchema):
    """Credenciales y CAPTCHA enviados a ``POST /auth/login``.

    ``identifier`` acepta el correo electrónico o el nombre de usuario. La
    contraseña se declara como ``SecretStr`` para que no se filtre en logs.
    """

    identifier: str = Field(
        min_length=1,
        max_length=255,
        description="Correo electrónico o nombre de usuario.",
        examples=["admin@synapsisx.com"],
    )
    password: SecretStr = Field(
        min_length=1,
        max_length=128,
        description="Contraseña del usuario (máximo 128 caracteres).",
    )
    captcha_token: str = Field(
        min_length=1,
        max_length=4096,
        description="Token devuelto por ``GET /auth/captcha``.",
    )
    captcha_answer: int | str = Field(
        description="Resultado de la suma del CAPTCHA (entero o cadena numérica).",
        examples=[19],
    )

    @field_validator("identifier", "captcha_token")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        """Recorta espacios accidentales y rechaza valores vacíos."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("El campo no puede estar vacío.")
        return normalized


class TokenResponse(UserSchema):
    """Par de tokens emitido tras un login correcto."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(
        description="Vigencia del access token en segundos.",
        examples=[1800],
    )


class LoginResponse(TokenResponse):
    """Tokens y permisos del rol, tal como exige el escenario 1 de la spec."""

    role: RoleEnum
    allowed_modules: list[str]


class RefreshRequest(UserSchema):
    """Refresh token enviado a ``POST /auth/refresh``."""

    refresh_token: SecretStr = Field(
        min_length=1,
        max_length=4096,
        description="Token de refresco emitido por el login.",
    )


class RefreshResponse(UserSchema):
    """Nuevo access token emitido al validar un refresh token."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(
        description="Vigencia del access token en segundos.",
        examples=[1800],
    )


class RoleResponse(UserSchema):
    """Rol funcional con su matriz de módulos permitidos."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    name: RoleEnum
    description: str
    allowed_modules: list[str]


class UserResponse(UserSchema):
    """Perfil público del usuario; nunca expone ``hashed_password``."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: UUID
    email: EmailStr
    username: str
    full_name: str
    is_active: bool
    role: RoleResponse
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- #
# Gestión de usuarios — /api/v1/users (consumidos en el Hito 4)
# --------------------------------------------------------------------------- #


class UserCreate(UserSchema):
    """Datos de alta de un usuario; el rol se referencia por UUID."""

    email: EmailStr = Field(max_length=255)
    username: str = Field(
        min_length=1,
        max_length=50,
        pattern=r"^[A-Za-z0-9]+$",
        description="Nombre de usuario alfanumérico.",
        examples=["jdoe"],
    )
    full_name: str = Field(min_length=1, max_length=150)
    password: StrongPassword = Field(description="Contraseña inicial.")
    role_id: UUID = Field(description="Rol existente que se asignará al usuario.")


class UserUpdate(UserSchema):
    """Actualización parcial de un usuario.

    Los campos privilegiados (``hashed_password``, ``failed_login_attempts``,
    ``locked_until``, ``role``) no están declarados y ``extra="forbid"`` los
    rechaza con 422.
    """

    email: EmailStr | None = Field(default=None, max_length=255)
    username: str | None = Field(
        default=None, min_length=1, max_length=50, pattern=r"^[A-Za-z0-9]+$"
    )
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    role_id: UUID | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _validate_partial_update(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Debes indicar al menos un campo para actualizar.")

        null_fields = [
            name
            for name in self.model_fields_set
            if getattr(self, name) is None
        ]
        if null_fields:
            raise ValueError(
                "Los campos " + ", ".join(sorted(null_fields)) + " no pueden ser nulos."
            )
        return self


class PasswordUpdate(UserSchema):
    """Restablecimiento de contraseña por parte de un administrador."""

    new_password: StrongPassword = Field(description="Nueva contraseña.")
