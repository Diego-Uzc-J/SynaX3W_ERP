"""Servicios de autenticación del módulo de Usuarios.

Implementa las reglas de ``specs/users_spec.md`` (secciones 4.1, 4.4 y 5.1):

* el CAPTCHA se valida **antes** de consultar credenciales;
* cinco intentos fallidos consecutivos bloquean la cuenta 15 minutos
  (``locked_until``);
* un usuario inexistente ejecuta una verificación Argon2id *dummy* y responde
  igual que una contraseña incorrecta (anti-enumeración y anti-timing);
* un login correcto reinicia el contador y emite ``access``/``refresh``;
* el refresco exige un ``refresh_token`` válido y una cuenta activa.

El módulo es agnóstico de HTTP: lanza excepciones de dominio que
``src.modules.users.router`` traduce a respuestas 400/401/403/423.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from src.core.config import settings
from src.core.security import (
    CAPTCHA_INVALID_DETAIL,
    INACTIVE_USER_DETAIL,
    INVALID_CREDENTIALS_DETAIL,
    INVALID_TOKEN_DETAIL,
    CaptchaError,
    TokenError,
    create_access_token,
    create_token_pair,
    decode_refresh_token,
    validate_captcha,
    verify_dummy_password,
    verify_password,
)
from src.modules.users.models import User

__all__ = [
    "ACCOUNT_LOCK_MINUTES",
    "MAX_FAILED_LOGIN_ATTEMPTS",
    "AccessTokenResult",
    "AccountLockedError",
    "CaptchaRejectedError",
    "InactiveUserError",
    "InvalidCredentialsError",
    "InvalidRefreshTokenError",
    "LoginResult",
    "UserServiceError",
    "authenticate_user",
    "refresh_access_token",
]

#: Intentos fallidos consecutivos antes de bloquear la cuenta.
MAX_FAILED_LOGIN_ATTEMPTS = 5

#: Duración del bloqueo temporal (sección 4.4).
ACCOUNT_LOCK_MINUTES = 15


# --------------------------------------------------------------------------- #
# Excepciones de dominio
# --------------------------------------------------------------------------- #


class UserServiceError(Exception):
    """Error base de autenticación del módulo ``users``."""

    default_detail = "Solicitud de autenticación inválida"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.default_detail
        super().__init__(self.detail)


class CaptchaRejectedError(UserServiceError):
    """El CAPTCHA faltó, fue manipulado, expiró o la suma es incorrecta."""

    default_detail = CAPTCHA_INVALID_DETAIL


class InvalidCredentialsError(UserServiceError):
    """Usuario inexistente o contraseña incorrecta (mensaje uniforme)."""

    default_detail = INVALID_CREDENTIALS_DETAIL


class AccountLockedError(UserServiceError):
    """La cuenta está bloqueada temporalmente por fuerza bruta."""

    default_detail = (
        "Cuenta bloqueada temporalmente por intentos fallidos. "
        f"Inténtalo de nuevo en {ACCOUNT_LOCK_MINUTES} minutos."
    )


class InactiveUserError(UserServiceError):
    """La cuenta existe pero está deshabilitada."""

    default_detail = INACTIVE_USER_DETAIL


class InvalidRefreshTokenError(UserServiceError):
    """El refresh token falta, expiró, fue manipulado o el usuario no existe."""

    default_detail = INVALID_TOKEN_DETAIL


# --------------------------------------------------------------------------- #
# Resultados
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class LoginResult:
    """Usuario autenticado y tokens emitidos."""

    user: User
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


@dataclass(frozen=True, slots=True)
class AccessTokenResult:
    """Nuevo access token emitido tras validar un refresh token."""

    access_token: str
    token_type: str
    expires_in: int


# --------------------------------------------------------------------------- #
# Utilidades internas
# --------------------------------------------------------------------------- #


def _utcnow() -> datetime:
    """Devuelve la fecha actual en UTC con zona horaria."""
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    """Normaliza fechas de SQLite (sin tz) antes de compararlas."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _find_user_for_login(db: Session, identifier: str) -> User | None:
    """Busca por correo o nombre de usuario y bloquea la fila para actualizar.

    ``SELECT ... FOR UPDATE`` serializa los intentos fallidos concurrentes en
    PostgreSQL. En SQLite (pruebas) el bloqueo se ignora de forma segura.
    """
    lookup = identifier.strip().lower()
    if not lookup:
        return None
    return db.scalar(
        select(User)
        .options(selectinload(User.role))
        .where(
            or_(
                User.email == lookup,
                func.lower(User.username) == lookup,
            )
        )
        .with_for_update()
    )


# --------------------------------------------------------------------------- #
# Login
# --------------------------------------------------------------------------- #


def authenticate_user(
    db: Session,
    *,
    identifier: str,
    password: str,
    captcha_token: str,
    captcha_answer: int | str,
) -> LoginResult:
    """Valida CAPTCHA y credenciales, aplica bloqueo y emite tokens.

    El CAPTCHA se comprueba **antes** de cualquier consulta al usuario o de
    verificar la contraseña, tal como exige la sección 4.1.

    Raises:
        CaptchaRejectedError: CAPTCHA inválido, expirado o suma incorrecta.
        InvalidCredentialsError: usuario inexistente o contraseña incorrecta.
        AccountLockedError: la cuenta sigue dentro del bloqueo de 15 minutos.
        InactiveUserError: credenciales correctas pero cuenta deshabilitada.
    """
    try:
        validate_captcha(captcha_token, captcha_answer)
    except CaptchaError as exc:
        # Se aborta antes de consultar la base de datos o el hash.
        raise CaptchaRejectedError(str(exc)) from exc

    user = _find_user_for_login(db, identifier)
    now = _utcnow()

    if user is None:
        # Mismo coste que una verificación real: mitiga timing/enumeración.
        verify_dummy_password()
        raise InvalidCredentialsError()

    if user.locked_until is not None:
        if _as_utc(user.locked_until) > now:
            raise AccountLockedError()
        # El bloqueo expiró: se limpia el estado para permitir nuevos intentos.
        user.locked_until = None
        user.failed_login_attempts = 0

    if not verify_password(password, user.hashed_password):
        user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
        if user.failed_login_attempts >= MAX_FAILED_LOGIN_ATTEMPTS:
            user.failed_login_attempts = 0
            user.locked_until = now + timedelta(minutes=ACCOUNT_LOCK_MINUTES)
        db.commit()
        # El quinto intento también responde 401 uniforme; el bloqueo se
        # manifiesta en el siguiente intento (incluso con contraseña correcta).
        raise InvalidCredentialsError()

    if not user.is_active:
        db.commit()
        raise InactiveUserError()

    # Login correcto: se reinicia el contador de fuerza bruta.
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()
    db.refresh(user)

    tokens = create_token_pair(user.id)
    return LoginResult(
        user=user,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
        expires_in=tokens.expires_in,
    )


# --------------------------------------------------------------------------- #
# Refresco de access token
# --------------------------------------------------------------------------- #


def refresh_access_token(db: Session, refresh_token: str) -> AccessTokenResult:
    """Valida un refresh token y emite un nuevo access token.

    Raises:
        InvalidRefreshTokenError: token inválido, expirado, de tipo incorrecto
            o asociado a un usuario inexistente.
        InactiveUserError: el usuario del token está deshabilitado.
    """
    try:
        payload = decode_refresh_token(refresh_token)
        user_id = uuid.UUID(str(payload["sub"]))
    except (TokenError, ValueError, TypeError, KeyError) as exc:
        raise InvalidRefreshTokenError() from exc

    user = db.scalar(
        select(User)
        .options(selectinload(User.role))
        .where(User.id == user_id)
    )
    if user is None:
        raise InvalidRefreshTokenError()
    if not user.is_active:
        raise InactiveUserError()

    return AccessTokenResult(
        access_token=create_access_token(user.id),
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )
