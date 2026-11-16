"""Núcleo de seguridad del ERP: contraseñas, JWT, CAPTCHA y RBAC.

Implementa los contratos de ``specs/users_spec.md`` (sección 4):

* **Contraseñas**: hashing y verificación con Argon2id mediante ``pwdlib``,
  además de una verificación *dummy* para igualar el coste cuando el usuario
  no existe (mitigación de *timing attacks*).
* **JWT**: emisión y decodificación estricta de ``access`` (30 min) y
  ``refresh`` (7 días) con ``PyJWT``. Se exigen los claims ``exp``, ``iat``,
  ``sub`` y ``type``.
* **CAPTCHA aritmético stateless**: suma de dos enteros generados con
  ``secrets.randbelow(20) + 1``, firmada con ``itsdangerous`` y válida durante
  180 segundos. La respuesta se compara con ``hmac.compare_digest``.
* **Dependencias FastAPI**: ``get_current_active_user`` y
  ``require_roles(...)``, con *bypass* automático para ``ADMINISTRATOR``.

Las funciones de bajo nivel lanzan excepciones de dominio
(``TokenError``, ``CaptchaError``, ``PasswordPolicyError``) para que la capa
de servicios pueda traducirlas a HTTP. Las dependencias FastAPI sí lanzan
``HTTPException`` con los códigos 401/403.
"""

from __future__ import annotations

import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any, Callable

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from itsdangerous import BadData, URLSafeTimedSerializer
from pwdlib import PasswordHash
from pwdlib.exceptions import HashVerificationError, UnknownHashError
from pwdlib.hashers.argon2 import Argon2Hasher
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from src.core.config import settings
from src.core.database import get_db
from src.modules.users.models import RoleEnum, User

# --------------------------------------------------------------------------- #
# Constantes y excepciones de dominio
# --------------------------------------------------------------------------- #

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128

TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"

INVALID_CREDENTIALS_DETAIL = "Credenciales inválidas"
INVALID_TOKEN_DETAIL = "Token inválido o expirado"
NOT_AUTHENTICATED_DETAIL = "No autenticado"
INACTIVE_USER_DETAIL = "Usuario inactivo"
FORBIDDEN_DETAIL = "No tienes permisos para acceder a este recurso"

CAPTCHA_SALT = "synapsisx-erp.users.captcha"
CAPTCHA_INVALID_DETAIL = "CAPTCHA inválido o expirado"


class PasswordPolicyError(ValueError):
    """La contraseña no cumple la política de la sección 4.2."""


class TokenError(Exception):
    """Token JWT ausente, malformado, expirado o de un tipo incorrecto."""


class CaptchaError(Exception):
    """CAPTCHA ausente, manipulado, expirado o con una respuesta incorrecta."""


# --------------------------------------------------------------------------- #
# Contraseñas (Argon2id)
# --------------------------------------------------------------------------- #

# ``Argon2Hasher`` usa Argon2id (``argon2.low_level.Type.ID``) por defecto.
_password_hasher = PasswordHash((Argon2Hasher(),))

#: Hash descartable generado una vez por proceso. Se usa para que un login con
#: usuario inexistente cueste lo mismo que uno con contraseña incorrecta.
_DUMMY_HASH = _password_hasher.hash(secrets.token_urlsafe(32))
_DUMMY_PROBE = "timing-attack-mitigation-probe"


def validate_password_strength(password: str) -> str:
    """Valida la política de contraseñas y devuelve el valor original.

    Reglas (sección 4.2): 10–128 caracteres y al menos una mayúscula, una
    minúscula, un número y un carácter especial.
    """
    if not isinstance(password, str):
        raise PasswordPolicyError("La contraseña debe ser una cadena de texto.")

    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(
            "La contraseña debe tener entre "
            f"{MIN_PASSWORD_LENGTH} y {MAX_PASSWORD_LENGTH} caracteres."
        )

    missing: list[str] = []
    if not any(char.isupper() for char in password):
        missing.append("una mayúscula")
    if not any(char.islower() for char in password):
        missing.append("una minúscula")
    if not any(char.isdigit() for char in password):
        missing.append("un número")
    if not any(not char.isalnum() for char in password):
        missing.append("un carácter especial")

    if missing:
        raise PasswordPolicyError(
            "La contraseña debe incluir " + ", ".join(missing) + "."
        )

    return password


def hash_password(password: str) -> str:
    """Genera un hash Argon2id, aplicando antes la política de contraseñas."""
    validate_password_strength(password)
    return _password_hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica una contraseña contra su hash Argon2id.

    Si el hash almacenado es inválido/desconocido se ejecuta igualmente una
    verificación dummy antes de devolver ``False``, para no filtrar por tiempo
    que el registro estaba corrupto.
    """
    if (
        not isinstance(plain_password, str)
        or len(plain_password) > MAX_PASSWORD_LENGTH
    ):
        verify_dummy_password()
        return False

    try:
        return _password_hasher.verify(plain_password, hashed_password)
    except (HashVerificationError, UnknownHashError, ValueError):
        verify_dummy_password()
        return False


def verify_dummy_password() -> None:
    """Ejecuta una verificación Argon2id descartable.

    Debe invocarse cuando el usuario no existe (o su hash no es válido) para
    que el tiempo de respuesta sea comparable al de una contraseña incorrecta.
    El resultado se ignora deliberadamente.
    """
    _password_hasher.verify(_DUMMY_PROBE, _DUMMY_HASH)


# --------------------------------------------------------------------------- #
# JWT (access + refresh)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class TokenPair:
    """Par de tokens emitido tras un login correcto."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 0


def _normalize_subject(subject: str | uuid.UUID) -> str:
    if subject is None:
        raise ValueError("El sujeto del token no puede estar vacío.")
    value = str(subject).strip()
    if not value:
        raise ValueError("El sujeto del token no puede estar vacío.")
    return value


def _encode_token(
    subject: str | uuid.UUID,
    token_type: str,
    expires_delta: timedelta,
) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": _normalize_subject(subject),
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def create_access_token(
    subject: str | uuid.UUID,
    expires_delta: timedelta | None = None,
) -> str:
    """Emite un token de acceso (30 minutos por defecto)."""
    delta = (
        expires_delta
        if expires_delta is not None
        else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return _encode_token(subject, TOKEN_TYPE_ACCESS, delta)


def create_refresh_token(
    subject: str | uuid.UUID,
    expires_delta: timedelta | None = None,
) -> str:
    """Emite un token de refresco (7 días por defecto)."""
    delta = (
        expires_delta
        if expires_delta is not None
        else timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )
    return _encode_token(subject, TOKEN_TYPE_REFRESH, delta)


def create_token_pair(subject: str | uuid.UUID) -> TokenPair:
    """Emite el par ``access``/``refresh`` para un usuario."""
    return TokenPair(
        access_token=create_access_token(subject),
        refresh_token=create_refresh_token(subject),
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    """Decodifica un JWT y valida firma, expiración, claims y tipo.

    Raises:
        TokenError: si el token falta, está expirado, tiene una firma
            inválida, no incluye los claims obligatorios o su ``type`` no
            coincide con ``expected_type``.
    """
    if not isinstance(token, str) or not token.strip():
        raise TokenError(INVALID_TOKEN_DETAIL)

    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "iat", "sub", "type"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError(INVALID_TOKEN_DETAIL) from exc

    token_type = payload.get("type")
    if token_type != expected_type:
        raise TokenError("Tipo de token inválido.")

    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise TokenError("El token no contiene un sujeto válido.")

    return payload


def decode_access_token(token: str) -> dict[str, Any]:
    """Decodifica y valida un token de acceso."""
    return decode_token(token, TOKEN_TYPE_ACCESS)


def decode_refresh_token(token: str) -> dict[str, Any]:
    """Decodifica y valida un token de refresco."""
    return decode_token(token, TOKEN_TYPE_REFRESH)


# --------------------------------------------------------------------------- #
# CAPTCHA aritmético stateless
# --------------------------------------------------------------------------- #

_captcha_serializer = URLSafeTimedSerializer(
    settings.CAPTCHA_SECRET_KEY,
    salt=CAPTCHA_SALT,
)


@dataclass(frozen=True, slots=True)
class CaptchaChallenge:
    """Desafío listo para enviar al cliente."""

    question: str
    captcha_token: str


def generate_captcha() -> CaptchaChallenge:
    """Genera una suma simple firmada y válida durante 180 segundos."""
    left = secrets.randbelow(20) + 1
    right = secrets.randbelow(20) + 1
    answer = left + right
    token = _captcha_serializer.dumps(
        {"answer": answer, "nonce": str(uuid.uuid4())}
    )
    return CaptchaChallenge(
        question=f"¿Cuánto es {left} + {right}?",
        captcha_token=token,
    )


def validate_captcha(captcha_token: str, captcha_answer: str | int) -> None:
    """Valida firma, antigüedad máxima (180 s) y respuesta del CAPTCHA.

    Raises:
        CaptchaError: ante cualquier token manipulado, expirado o respuesta
            incorrecta. El mensaje es siempre genérico para no dar pistas.
    """
    if not isinstance(captcha_token, str) or not captcha_token.strip():
        raise CaptchaError(CAPTCHA_INVALID_DETAIL)

    try:
        payload = _captcha_serializer.loads(
            captcha_token,
            max_age=settings.CAPTCHA_MAX_AGE_SECONDS,
        )
    except BadData as exc:
        raise CaptchaError(CAPTCHA_INVALID_DETAIL) from exc

    if not isinstance(payload, dict):
        raise CaptchaError(CAPTCHA_INVALID_DETAIL)

    expected = payload.get("answer")
    nonce = payload.get("nonce")
    if (
        isinstance(expected, bool)
        or not isinstance(expected, int)
        or not isinstance(nonce, str)
        or not nonce
    ):
        raise CaptchaError(CAPTCHA_INVALID_DETAIL)

    if isinstance(captcha_answer, bool):
        raise CaptchaError(CAPTCHA_INVALID_DETAIL)

    if isinstance(captcha_answer, int):
        provided = captcha_answer
    elif isinstance(captcha_answer, str):
        try:
            provided = int(captcha_answer.strip())
        except ValueError as exc:
            raise CaptchaError(CAPTCHA_INVALID_DETAIL) from exc
    else:
        raise CaptchaError(CAPTCHA_INVALID_DETAIL)

    if not hmac.compare_digest(str(expected), str(provided)):
        raise CaptchaError(CAPTCHA_INVALID_DETAIL)


# --------------------------------------------------------------------------- #
# Dependencias FastAPI: autenticación y RBAC
# --------------------------------------------------------------------------- #

bearer_scheme = HTTPBearer(
    auto_error=False,
    description="JWT de acceso emitido por /api/v1/users/auth/login",
)


def _unauthorized(detail: str = NOT_AUTHENTICATED_DETAIL) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
    ],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Resuelve el usuario autenticado a partir del ``access_token``.

    No comprueba ``is_active``; eso queda en ``get_current_active_user`` para
    que los endpoints puedan distinguir autenticación de autorización.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()

    try:
        payload = decode_access_token(credentials.credentials)
        user_id = uuid.UUID(payload["sub"])
    except (TokenError, ValueError, TypeError):
        raise _unauthorized(INVALID_TOKEN_DETAIL) from None

    user = db.scalar(
        select(User)
        .options(joinedload(User.role))
        .where(User.id == user_id)
    )
    if user is None:
        raise _unauthorized(INVALID_TOKEN_DETAIL)

    return user


def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Devuelve el usuario autenticado solo si su cuenta está activa."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=INACTIVE_USER_DETAIL,
        )
    return current_user


def require_roles(allowed_roles: list[RoleEnum]) -> Callable[..., User]:
    """Crea una dependencia que exige uno de los roles indicados.

    ``ADMINISTRATOR`` siempre pasa (*superuser bypass*), según la sección 4.3.
    """
    allowed = frozenset(allowed_roles)

    def dependency(
        current_user: Annotated[User, Depends(get_current_active_user)],
    ) -> User:
        role = current_user.role.name
        if role is RoleEnum.ADMINISTRATOR or role in allowed:
            return current_user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=FORBIDDEN_DETAIL,
        )

    return dependency


__all__ = [
    "CAPTCHA_INVALID_DETAIL",
    "CAPTCHA_SALT",
    "CaptchaChallenge",
    "CaptchaError",
    "FORBIDDEN_DETAIL",
    "INACTIVE_USER_DETAIL",
    "INVALID_CREDENTIALS_DETAIL",
    "INVALID_TOKEN_DETAIL",
    "MAX_PASSWORD_LENGTH",
    "MIN_PASSWORD_LENGTH",
    "NOT_AUTHENTICATED_DETAIL",
    "PasswordPolicyError",
    "TOKEN_TYPE_ACCESS",
    "TOKEN_TYPE_REFRESH",
    "TokenError",
    "TokenPair",
    "bearer_scheme",
    "create_access_token",
    "create_refresh_token",
    "create_token_pair",
    "decode_access_token",
    "decode_refresh_token",
    "decode_token",
    "generate_captcha",
    "get_current_active_user",
    "get_current_user",
    "hash_password",
    "require_roles",
    "validate_captcha",
    "validate_password_strength",
    "verify_dummy_password",
    "verify_password",
]
