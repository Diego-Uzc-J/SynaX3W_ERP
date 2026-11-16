"""Pruebas del flujo de autenticación del módulo ``users`` (Hito 3).

Cubre los contratos de ``specs/users_spec.md`` (secciones 4.1, 4.2, 4.4 y
5.1) sobre la API HTTP real:

* CAPTCHA obligatorio antes de validar credenciales;
* respuesta uniforme 401 y verificación dummy para usuarios inexistentes;
* bloqueo de 15 minutos tras cinco fallos consecutivos;
* emisión/renovación de tokens y perfil ``/me`` sin ``hashed_password``;
* límites de ``slowapi`` (15/min captcha, 5/min login);
* rechazo de asignación masiva y contraseñas débiles en los esquemas.

La suite OWASP completa (7 escenarios) se reserva para
``backend/tests/test_users_security.py`` en el Hito 6.
"""

from __future__ import annotations

import os
import re
import sys
import uuid
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# ``backend`` debe estar en sys.path para importar el paquete ``src``.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# El engine global de ``src.core.database`` se crea al importar.
os.environ["DATABASE_URL"] = "sqlite://"

from src.core.config import settings  # noqa: E402
from src.core.database import Base, get_db  # noqa: E402
from src.core.security import (  # noqa: E402
    INVALID_CREDENTIALS_DETAIL,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    hash_password,
)
from src.modules.users import services  # noqa: E402
from src.modules.users.models import Role, RoleEnum, User  # noqa: E402
from src.modules.users.router import (  # noqa: E402
    limiter,
    router as users_router,
    users_exception_handler,
)
from src.modules.users.schemas import (  # noqa: E402
    LoginRequest,
    PasswordUpdate,
    UserCreate,
    UserResponse,
    UserUpdate,
)
from src.modules.users.services import UserServiceError  # noqa: E402

CAPTCHA_URL = "/api/v1/users/auth/captcha"
LOGIN_URL = "/api/v1/users/auth/login"
REFRESH_URL = "/api/v1/users/auth/refresh"
ME_URL = "/api/v1/users/auth/me"

_PASSWORD = "Valid1234!"
_HASHED_PASSWORD = hash_password(_PASSWORD)
_CAPTCHA_PATTERN = re.compile(r"^¿Cuánto es (\d+) \+ (\d+)\?$")


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture()
def db_engine() -> Generator[Engine, None, None]:
    """Engine SQLite en memoria compartido por las sesiones de la prueba."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def db_session(db_engine: Engine) -> Generator[Session, None, None]:
    session_factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    with session_factory() as session:
        yield session


@pytest.fixture()
def api(db_engine: Engine) -> Generator[TestClient, None, None]:
    """App FastAPI con el router real y una base SQLite aislada."""
    session_factory = sessionmaker(bind=db_engine, expire_on_commit=False)

    def _override_get_db() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_exception_handler(UserServiceError, users_exception_handler)
    app.include_router(users_router, prefix="/api/v1/users")
    app.dependency_overrides[get_db] = _override_get_db

    limiter.reset()
    try:
        with TestClient(app) as client:
            yield client
    finally:
        limiter.reset()


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #


def _role(db: Session, role_enum: RoleEnum) -> Role:
    role = db.scalar(select(Role).where(Role.name == role_enum))
    if role is None:
        role = Role(
            name=role_enum,
            description=role_enum.value,
            allowed_modules=[],
        )
        db.add(role)
        db.flush()
    return role


def _create_user(
    db: Session,
    *,
    role_enum: RoleEnum = RoleEnum.SALES,
    email: str = "sales@example.com",
    username: str = "salesuser",
    is_active: bool = True,
    allowed_modules: list[str] | None = None,
) -> User:
    role = _role(db, role_enum)
    if allowed_modules is not None:
        role.allowed_modules = allowed_modules
        db.add(role)
        db.flush()

    user = User(
        email=email,
        username=username,
        full_name=username.replace("_", " ").title(),
        hashed_password=_HASHED_PASSWORD,
        role_id=role.id,
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _captcha(api: TestClient) -> tuple[dict[str, str], int]:
    response = api.get(CAPTCHA_URL)
    assert response.status_code == 200, response.text
    body = response.json()

    match = _CAPTCHA_PATTERN.fullmatch(body["question"])
    assert match is not None, body["question"]
    left, right = (int(value) for value in match.groups())
    assert 1 <= left <= 20 and 1 <= right <= 20
    return body, left + right


def _login(
    api: TestClient,
    *,
    identifier: str,
    password: str = _PASSWORD,
    captcha: tuple[dict[str, str], int] | None = None,
    answer_delta: int = 0,
):
    challenge, answer = captcha or _captcha(api)
    return api.post(
        LOGIN_URL,
        json={
            "identifier": identifier,
            "password": password,
            "captcha_token": challenge["captcha_token"],
            "captcha_answer": answer + answer_delta,
        },
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# CAPTCHA
# --------------------------------------------------------------------------- #


def test_captcha_endpoint_returns_signed_challenge(api: TestClient) -> None:
    body, answer = _captcha(api)

    assert set(body) == {"question", "captcha_token"}
    assert 2 <= answer <= 40
    assert body["question"].startswith("¿Cuánto es ")
    assert body["captcha_token"]


def test_login_rejects_wrong_and_tampered_captcha_before_credentials(
    api: TestClient, db_session: Session
) -> None:
    user = _create_user(db_session)

    wrong = _login(api, identifier=user.email, answer_delta=1)
    assert wrong.status_code == 400
    assert wrong.json()["detail"] == "CAPTCHA inválido o expirado"

    challenge, answer = _captcha(api)
    tampered = api.post(
        LOGIN_URL,
        json={
            "identifier": user.email,
            "password": _PASSWORD,
            "captcha_token": challenge["captcha_token"] + "x",
            "captcha_answer": answer,
        },
    )
    assert tampered.status_code == 400

    # El CAPTCHA se rechaza antes de tocar el contador de intentos.
    db_session.refresh(user)
    assert user.failed_login_attempts == 0
    assert user.locked_until is None


def test_login_rejects_expired_captcha(
    api: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _create_user(db_session)
    challenge, answer = _captcha(api)
    monkeypatch.setattr(settings, "CAPTCHA_MAX_AGE_SECONDS", -1)

    response = _login(
        api,
        identifier=user.email,
        captcha=(challenge, answer),
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "CAPTCHA inválido o expirado"
    assert "access_token" not in response.text


# --------------------------------------------------------------------------- #
# Login
# --------------------------------------------------------------------------- #


def test_login_success_returns_tokens_role_and_permissions(
    api: TestClient, db_session: Session
) -> None:
    user = _create_user(
        db_session,
        allowed_modules=["sales", "inventory:read"],
    )

    response = _login(api, identifier=user.email)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 30 * 60
    assert body["role"] == "sales"
    assert body["allowed_modules"] == ["sales", "inventory:read"]
    assert "hashed_password" not in response.text

    access = decode_access_token(body["access_token"])
    refresh = decode_refresh_token(body["refresh_token"])
    assert access["sub"] == str(user.id)
    assert refresh["sub"] == str(user.id)
    assert access["type"] == "access"
    assert refresh["type"] == "refresh"

    db_session.refresh(user)
    assert user.failed_login_attempts == 0
    assert user.locked_until is None


def test_login_accepts_username_as_identifier(
    api: TestClient, db_session: Session
) -> None:
    user = _create_user(db_session)

    response = _login(api, identifier=user.username.upper())

    assert response.status_code == 200, response.text
    assert response.json()["role"] == "sales"


def test_invalid_credentials_are_uniform_and_use_dummy_hash(
    api: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = _create_user(db_session)
    dummy_calls: list[None] = []
    monkeypatch.setattr(
        services,
        "verify_dummy_password",
        lambda: dummy_calls.append(None),
    )

    unknown = _login(api, identifier="nobody@example.com")
    wrong_password = _login(
        api,
        identifier=user.email,
        password="Wrong1234!",
    )

    for response in (unknown, wrong_password):
        assert response.status_code == 401
        assert response.json()["detail"] == INVALID_CREDENTIALS_DETAIL
        assert response.headers["www-authenticate"] == "Bearer"
        assert "access_token" not in response.text

    # Solo el usuario inexistente ejecuta la verificación dummy.
    assert len(dummy_calls) == 1


def test_account_locks_after_five_failed_attempts(
    api: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # El límite de 5/min impediría llegar al sexto intento en esta prueba.
    monkeypatch.setattr(limiter, "enabled", False)
    user = _create_user(db_session)

    for _ in range(5):
        response = _login(
            api,
            identifier=user.email,
            password="Wrong1234!",
        )
        assert response.status_code == 401
        assert response.json()["detail"] == INVALID_CREDENTIALS_DETAIL

    db_session.refresh(user)
    assert user.failed_login_attempts == 0
    assert user.locked_until is not None
    if user.locked_until.tzinfo is None:
        locked_until = user.locked_until.replace(tzinfo=timezone.utc)
    else:
        locked_until = user.locked_until
    remaining = locked_until - datetime.now(timezone.utc)
    assert timedelta(minutes=14) < remaining <= timedelta(minutes=15)

    # Incluso con la contraseña correcta, el bloqueo impide emitir tokens.
    blocked = _login(api, identifier=user.email)
    assert blocked.status_code == 423
    assert "bloqueada" in blocked.json()["detail"].lower()
    assert "access_token" not in blocked.text


def test_expired_lock_allows_login_again(
    api: TestClient, db_session: Session
) -> None:
    user = _create_user(db_session)
    user.failed_login_attempts = 5
    user.locked_until = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.add(user)
    db_session.commit()

    response = _login(api, identifier=user.email)

    assert response.status_code == 200, response.text
    db_session.refresh(user)
    assert user.failed_login_attempts == 0
    assert user.locked_until is None


def test_inactive_user_with_correct_password_is_forbidden(
    api: TestClient, db_session: Session
) -> None:
    user = _create_user(db_session, is_active=False)

    response = _login(api, identifier=user.email)

    assert response.status_code == 403
    assert response.json()["detail"] == "Usuario inactivo"
    assert "access_token" not in response.text


# --------------------------------------------------------------------------- #
# Refresh y perfil
# --------------------------------------------------------------------------- #


def test_refresh_emits_new_access_token(
    api: TestClient, db_session: Session
) -> None:
    user = _create_user(db_session)
    login = _login(api, identifier=user.email)
    assert login.status_code == 200
    refresh_token = login.json()["refresh_token"]

    response = api.post(
        REFRESH_URL, json={"refresh_token": refresh_token}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 30 * 60
    access = decode_access_token(body["access_token"])
    assert access["sub"] == str(user.id)

    # Un access token no sirve como refresh token.
    invalid_type = api.post(
        REFRESH_URL,
        json={"refresh_token": login.json()["access_token"]},
    )
    assert invalid_type.status_code == 401

    malformed = api.post(
        REFRESH_URL, json={"refresh_token": "not-a-token"}
    )
    assert malformed.status_code == 401


def test_refresh_rejects_inactive_or_unknown_users(
    api: TestClient, db_session: Session
) -> None:
    inactive = _create_user(
        db_session,
        email="inactive@example.com",
        username="inactiveuser",
        is_active=False,
    )
    inactive_response = api.post(
        REFRESH_URL,
        json={"refresh_token": create_refresh_token(inactive.id)},
    )
    assert inactive_response.status_code == 403

    unknown_response = api.post(
        REFRESH_URL,
        json={"refresh_token": create_refresh_token(uuid.uuid4())},
    )
    assert unknown_response.status_code == 401


def test_me_returns_profile_role_and_modules_without_hash(
    api: TestClient, db_session: Session
) -> None:
    user = _create_user(
        db_session,
        allowed_modules=["sales", "inventory:read"],
    )
    login = _login(api, identifier=user.email)
    access_token = login.json()["access_token"]

    response = api.get(ME_URL, headers=_auth(access_token))

    assert response.status_code == 200, response.text
    assert "hashed_password" not in response.text
    body = response.json()
    assert body["id"] == str(user.id)
    assert body["email"] == user.email
    assert body["username"] == user.username
    assert body["is_active"] is True
    assert body["role"]["name"] == "sales"
    assert body["role"]["allowed_modules"] == ["sales", "inventory:read"]
    assert set(body) == {
        "id",
        "email",
        "username",
        "full_name",
        "is_active",
        "role",
        "created_at",
        "updated_at",
    }


# --------------------------------------------------------------------------- #
# Rate limiting (slowapi)
# --------------------------------------------------------------------------- #


def test_captcha_rate_limit_is_fifteen_per_minute(api: TestClient) -> None:
    for _ in range(15):
        assert api.get(CAPTCHA_URL).status_code == 200

    exceeded = api.get(CAPTCHA_URL)
    assert exceeded.status_code == 429


def test_login_rate_limit_is_five_per_minute(api: TestClient) -> None:
    statuses = []
    for _ in range(6):
        statuses.append(
            _login(api, identifier="nobody@example.com").status_code
        )

    assert statuses[:5] == [401] * 5
    assert statuses[5] == 429


# --------------------------------------------------------------------------- #
# Esquemas: asignación masiva y política de contraseñas
# --------------------------------------------------------------------------- #


def test_schemas_reject_mass_assignment_and_weak_passwords(
    db_session: Session,
) -> None:
    with pytest.raises(ValidationError):
        LoginRequest(
            identifier="admin@example.com",
            password=_PASSWORD,
            captcha_token="token",
            captcha_answer=19,
            hashed_password="injected",
        )

    with pytest.raises(ValidationError):
        UserUpdate(failed_login_attempts=0)

    with pytest.raises(ValidationError):
        UserUpdate()

    with pytest.raises(ValidationError):
        UserCreate(
            email="nuevo@example.com",
            username="nuevouser",
            full_name="Nuevo Usuario",
            password="weak",
            role_id=uuid.uuid4(),
        )

    with pytest.raises(ValidationError):
        PasswordUpdate(new_password="NoSpecial123")

    user = _create_user(db_session)
    payload = UserResponse.model_validate(user).model_dump()
    assert "hashed_password" not in payload
    assert "hashed_password" not in UserResponse.model_fields


# --------------------------------------------------------------------------- #
# Integración con la app principal
# --------------------------------------------------------------------------- #


def test_main_app_registers_users_routes_and_limiter() -> None:
    from src.main import app as main_app

    paths = main_app.openapi()["paths"]
    for path in (CAPTCHA_URL, LOGIN_URL, REFRESH_URL, ME_URL):
        assert path in paths

    assert main_app.state.limiter is limiter
