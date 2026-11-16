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
from sqlalchemy.exc import IntegrityError
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
    hash_password,
    validate_captcha,
    verify_dummy_password,
    verify_password,
)
from src.modules.users.models import Role, RoleEnum, User
from src.modules.users.schemas import PasswordUpdate, UserCreate, UserUpdate

__all__ = [
    "ACCOUNT_LOCK_MINUTES",
    "MAX_FAILED_LOGIN_ATTEMPTS",
    "AccessTokenResult",
    "AccountLockedError",
    "CaptchaRejectedError",
    "DuplicateUserError",
    "InactiveUserError",
    "InvalidCredentialsError",
    "InvalidRefreshTokenError",
    "LoginResult",
    "RoleNotFoundError",
    "UserNotFoundError",
    "UserServiceError",
    "authenticate_user",
    "create_user",
    "list_roles",
    "list_users",
    "refresh_access_token",
    "reset_user_password",
    "update_user",
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


class UserNotFoundError(UserServiceError):
    """El usuario solicitado no existe."""

    default_detail = "Usuario no encontrado"


class RoleNotFoundError(UserServiceError):
    """El rol referenciado no existe en el catálogo maestro."""

    default_detail = "Rol no encontrado"


class DuplicateUserError(UserServiceError):
    """Ya existe otra cuenta con el mismo correo o nombre de usuario."""

    default_detail = "Ya existe un usuario con ese correo o nombre de usuario"


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


# --------------------------------------------------------------------------- #
# Administración de usuarios y roles (sección 5.2)
# --------------------------------------------------------------------------- #


def _get_user_or_404(db: Session, user_id: uuid.UUID) -> User:
    """Carga un usuario con su rol o lanza ``UserNotFoundError``."""
    user = db.scalar(
        select(User)
        .options(selectinload(User.role))
        .where(User.id == user_id)
    )
    if user is None:
        raise UserNotFoundError()
    return user


def _get_role_or_404(db: Session, role_id: uuid.UUID) -> Role:
    """Devuelve el rol solicitado o lanza ``RoleNotFoundError``."""
    role = db.get(Role, role_id)
    if role is None:
        raise RoleNotFoundError()
    return role


def _escape_like(value: str) -> str:
    """Neutraliza los comodines de ``LIKE`` para que la búsqueda sea literal."""
    return (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def _ensure_identity_available(
    db: Session,
    *,
    email: str | None = None,
    username: str | None = None,
    exclude_id: uuid.UUID | None = None,
) -> None:
    """Comprueba de forma insensible a mayúsculas que correo/usuario no existan.

    La consulta se construye con parámetros ligados por SQLAlchemy; nunca se
    interpola texto del cliente en SQL (OWASP A03).
    """
    conditions = []
    if email is not None:
        conditions.append(func.lower(User.email) == email.strip().lower())
    if username is not None:
        conditions.append(func.lower(User.username) == username.strip().lower())
    if not conditions:
        return

    statement = select(User.id).where(or_(*conditions))
    if exclude_id is not None:
        statement = statement.where(User.id != exclude_id)
    if db.scalar(statement) is not None:
        raise DuplicateUserError()


def list_roles(db: Session) -> list[Role]:
    """Devuelve el catálogo completo de roles y sus módulos permitidos."""
    return list(db.scalars(select(Role).order_by(Role.name)).all())


def create_user(db: Session, payload: UserCreate) -> User:
    """Crea un usuario con un ``role_id`` existente y contraseña Argon2id.

    Raises:
        RoleNotFoundError: el ``role_id`` no pertenece al catálogo de roles.
        DuplicateUserError: ya existe una cuenta con ese correo o usuario.
    """
    role = _get_role_or_404(db, payload.role_id)
    email = str(payload.email).strip().lower()
    username = payload.username.strip()
    _ensure_identity_available(db, email=email, username=username)

    user = User(
        email=email,
        username=username,
        full_name=payload.full_name.strip(),
        hashed_password=hash_password(payload.password.get_secret_value()),
        role=role,
        is_active=True,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # Carrera entre la comprobación previa y el INSERT: la unicidad de la
        # base de datos sigue siendo la última línea de defensa.
        raise DuplicateUserError() from exc

    return _get_user_or_404(db, user.id)


def list_users(
    db: Session,
    *,
    skip: int = 0,
    limit: int = 100,
    role: RoleEnum | None = None,
    is_active: bool | None = None,
    search: str | None = None,
) -> list[User]:
    """Lista usuarios con paginación y filtros seguros por rol, estado y texto."""
    statement = select(User).options(selectinload(User.role))

    if role is not None:
        statement = statement.where(User.role.has(Role.name == role))
    if is_active is not None:
        statement = statement.where(User.is_active.is_(is_active))
    if search is not None and search.strip():
        pattern = f"%{_escape_like(search.strip())}%"
        statement = statement.where(
            or_(
                User.email.ilike(pattern, escape="\\"),
                User.username.ilike(pattern, escape="\\"),
                User.full_name.ilike(pattern, escape="\\"),
            )
        )

    statement = (
        statement.order_by(User.created_at.desc(), User.email.asc())
        .offset(skip)
        .limit(limit)
    )
    return list(db.scalars(statement).all())


def update_user(
    db: Session,
    user_id: uuid.UUID,
    payload: UserUpdate,
) -> User:
    """Actualiza datos, rol o estado de una cuenta existente.

    Sólo se aplican los campos enviados (``exclude_unset``). Los campos
    privilegiados no existen en ``UserUpdate`` y ``extra="forbid"`` los
    rechaza antes de llegar aquí.

    Raises:
        UserNotFoundError: el usuario no existe.
        RoleNotFoundError: el nuevo ``role_id`` no existe.
        DuplicateUserError: el nuevo correo o usuario ya está en uso.
    """
    user = _get_user_or_404(db, user_id)
    changes = payload.model_dump(exclude_unset=True)
    role_id = changes.pop("role_id", None)

    if "email" in changes:
        changes["email"] = str(changes["email"]).strip().lower()
    if "username" in changes:
        changes["username"] = changes["username"].strip()
    if "full_name" in changes:
        changes["full_name"] = changes["full_name"].strip()

    _ensure_identity_available(
        db,
        email=changes.get("email"),
        username=changes.get("username"),
        exclude_id=user.id,
    )

    role = _get_role_or_404(db, role_id) if role_id is not None else None
    for field, value in changes.items():
        setattr(user, field, value)
    if role is not None:
        user.role = role

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateUserError() from exc

    return _get_user_or_404(db, user.id)


def reset_user_password(
    db: Session,
    user_id: uuid.UUID,
    payload: PasswordUpdate,
) -> User:
    """Restablece la contraseña y limpia el bloqueo por fuerza bruta.

    Un restablecimiento administrativo debe devolver la cuenta a un estado
    utilizable, por lo que también reinicia ``failed_login_attempts`` y
    ``locked_until``.

    Raises:
        UserNotFoundError: el usuario no existe.
    """
    user = _get_user_or_404(db, user_id)
    user.hashed_password = hash_password(payload.new_password.get_secret_value())
    user.failed_login_attempts = 0
    user.locked_until = None
    db.commit()
    return _get_user_or_404(db, user.id)
