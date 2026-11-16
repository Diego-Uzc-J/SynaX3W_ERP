"""Routers FastAPI del módulo de Usuarios: autenticación y perfil.

Expone los contratos de ``specs/users_spec.md`` (sección 5.1). El prefijo
``/api/v1/users`` se aplica al registrar este router en ``src.main``, por lo
que las rutas finales son:

* ``GET  /api/v1/users/auth/captcha`` (15 peticiones/minuto)
* ``POST /api/v1/users/auth/login`` (5 peticiones/minuto)
* ``POST /api/v1/users/auth/refresh``
* ``GET  /api/v1/users/auth/me``

``users_exception_handler`` traduce las excepciones de ``services.py`` a
HTTP 400/401/403/423. Las respuestas 401 incluyen ``WWW-Authenticate: Bearer``.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request, Response, status
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.security import (
    generate_captcha,
    get_current_active_user,
    require_roles,
)
from src.modules.users import services
from src.modules.users.models import RoleEnum, User
from src.modules.users.schemas import (
    CaptchaResponse,
    LoginRequest,
    LoginResponse,
    PasswordUpdate,
    RefreshRequest,
    RefreshResponse,
    RoleResponse,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from src.modules.users.services import (
    AccountLockedError,
    CaptchaRejectedError,
    DuplicateUserError,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    RoleNotFoundError,
    UserNotFoundError,
    UserServiceError,
)

__all__ = [
    "admin_router",
    "auth_router",
    "limiter",
    "router",
    "users_exception_handler",
]


#: Limitador compartido con ``src.main`` (se registra en ``app.state.limiter``).
limiter = Limiter(
    key_func=get_remote_address,
    headers_enabled=True,
)


_ERROR_STATUS: tuple[tuple[type[UserServiceError], int], ...] = (
    (CaptchaRejectedError, status.HTTP_400_BAD_REQUEST),
    (InvalidCredentialsError, status.HTTP_401_UNAUTHORIZED),
    (InvalidRefreshTokenError, status.HTTP_401_UNAUTHORIZED),
    (AccountLockedError, status.HTTP_423_LOCKED),
    (InactiveUserError, status.HTTP_403_FORBIDDEN),
    (UserNotFoundError, status.HTTP_404_NOT_FOUND),
    (RoleNotFoundError, status.HTTP_404_NOT_FOUND),
    (DuplicateUserError, status.HTTP_409_CONFLICT),
)

_AUTHENTICATION_ERRORS = (InvalidCredentialsError, InvalidRefreshTokenError)


async def users_exception_handler(
    request: Request, exc: UserServiceError
) -> JSONResponse:
    """Convierte un error de autenticación en una respuesta HTTP uniforme."""
    status_code = next(
        (
            code
            for error_class, code in _ERROR_STATUS
            if isinstance(exc, error_class)
        ),
        status.HTTP_400_BAD_REQUEST,
    )
    headers = (
        {"WWW-Authenticate": "Bearer"}
        if isinstance(exc, _AUTHENTICATION_ERRORS)
        else None
    )
    return JSONResponse(
        status_code=status_code,
        content={"detail": exc.detail},
        headers=headers,
    )


auth_router = APIRouter(prefix="/auth", tags=["users: auth"])


@auth_router.get(
    "/captcha",
    response_model=CaptchaResponse,
    status_code=status.HTTP_200_OK,
    summary="Generar un CAPTCHA aritmético",
)
@limiter.limit("15/minute")
def get_captcha(request: Request, response: Response) -> CaptchaResponse:
    """Devuelve una suma firmada y válida durante 180 segundos."""
    challenge = generate_captcha()
    return CaptchaResponse(
        question=challenge.question,
        captcha_token=challenge.captcha_token,
    )


@auth_router.post(
    "/login",
    response_model=LoginResponse,
    status_code=status.HTTP_200_OK,
    summary="Iniciar sesión",
)
@limiter.limit("5/minute")
def login(
    request: Request,
    response: Response,
    payload: LoginRequest,
    db: Session = Depends(get_db),
) -> LoginResponse:
    """Valida CAPTCHA y credenciales, aplica bloqueo y emite tokens."""
    result = services.authenticate_user(
        db,
        identifier=payload.identifier,
        password=payload.password.get_secret_value(),
        captcha_token=payload.captcha_token,
        captcha_answer=payload.captcha_answer,
    )
    return LoginResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        token_type=result.token_type,
        expires_in=result.expires_in,
        role=result.user.role.name,
        allowed_modules=list(result.user.role.allowed_modules),
    )


@auth_router.post(
    "/refresh",
    response_model=RefreshResponse,
    status_code=status.HTTP_200_OK,
    summary="Renovar el access token",
)
def refresh(
    payload: RefreshRequest,
    db: Session = Depends(get_db),
) -> RefreshResponse:
    """Valida el refresh token y la cuenta antes de emitir un nuevo access."""
    result = services.refresh_access_token(
        db, payload.refresh_token.get_secret_value()
    )
    return RefreshResponse(
        access_token=result.access_token,
        token_type=result.token_type,
        expires_in=result.expires_in,
    )


@auth_router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener el perfil autenticado",
)
def me(
    current_user: Annotated[User, Depends(get_current_active_user)],
) -> UserResponse:
    """Devuelve perfil, rol y módulos permitidos; nunca el hash de contraseña."""
    return UserResponse.model_validate(current_user)


# --------------------------------------------------------------------------- #
# Administración — /api/v1/users (solo ADMINISTRATOR)
# --------------------------------------------------------------------------- #

#: Todas las rutas administrativas comparten la misma guardia RBAC. El
#: ``ADMINISTRATOR`` pasa siempre gracias al bypass interno de ``require_roles``.
admin_only = require_roles([RoleEnum.ADMINISTRATOR])

admin_router = APIRouter(tags=["users: admin"])


@admin_router.get(
    "/roles",
    response_model=list[RoleResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar roles y sus módulos permitidos",
)
def list_roles(
    _admin: Annotated[User, Depends(admin_only)],
    db: Session = Depends(get_db),
) -> list[RoleResponse]:
    """Catálogo maestro de roles (sección 5.2)."""
    return [
        RoleResponse.model_validate(role) for role in services.list_roles(db)
    ]


@admin_router.post(
    "/",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un usuario",
)
def create_user(
    payload: UserCreate,
    _admin: Annotated[User, Depends(admin_only)],
    db: Session = Depends(get_db),
) -> UserResponse:
    """Crea la cuenta con un ``role_id`` existente y contraseña Argon2id."""
    user = services.create_user(db, payload)
    return UserResponse.model_validate(user)


@admin_router.get(
    "/",
    response_model=list[UserResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar usuarios",
)
def list_users(
    _admin: Annotated[User, Depends(admin_only)],
    skip: int = Query(0, ge=0, description="Registros a omitir."),
    limit: int = Query(100, ge=1, le=200, description="Máximo de registros."),
    role: RoleEnum | None = Query(None, description="Filtro por rol."),
    is_active: bool | None = Query(None, description="Filtro por estado."),
    search: str | None = Query(
        None,
        max_length=150,
        description="Búsqueda literal por correo, usuario o nombre.",
    ),
    db: Session = Depends(get_db),
) -> list[UserResponse]:
    """Lista paginada con filtros parametrizados por rol, estado y texto."""
    users = services.list_users(
        db,
        skip=skip,
        limit=limit,
        role=role,
        is_active=is_active,
        search=search,
    )
    return [UserResponse.model_validate(user) for user in users]


@admin_router.patch(
    "/{user_id}",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Actualizar un usuario",
)
def update_user(
    payload: UserUpdate,
    _admin: Annotated[User, Depends(admin_only)],
    user_id: UUID = Path(..., description="Identificador del usuario."),
    db: Session = Depends(get_db),
) -> UserResponse:
    """Actualiza datos, rol o ``is_active`` de una cuenta existente."""
    user = services.update_user(db, user_id, payload)
    return UserResponse.model_validate(user)


@admin_router.patch(
    "/{user_id}/password",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Restablecer la contraseña de un usuario",
)
def reset_user_password(
    payload: PasswordUpdate,
    _admin: Annotated[User, Depends(admin_only)],
    user_id: UUID = Path(..., description="Identificador del usuario."),
    db: Session = Depends(get_db),
) -> UserResponse:
    """Restablece la contraseña y limpia el bloqueo por fuerza bruta."""
    user = services.reset_user_password(db, user_id, payload)
    return UserResponse.model_validate(user)


# --------------------------------------------------------------------------- #
# Router agregado
# --------------------------------------------------------------------------- #

router = APIRouter()
router.include_router(auth_router)
router.include_router(admin_router)
