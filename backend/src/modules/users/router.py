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

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.security import generate_captcha, get_current_active_user
from src.modules.users import services
from src.modules.users.models import User
from src.modules.users.schemas import (
    CaptchaResponse,
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    RefreshResponse,
    UserResponse,
)
from src.modules.users.services import (
    AccountLockedError,
    CaptchaRejectedError,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    UserServiceError,
)

__all__ = ["auth_router", "limiter", "router", "users_exception_handler"]


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
# Router agregado
# --------------------------------------------------------------------------- #

router = APIRouter()
router.include_router(auth_router)
