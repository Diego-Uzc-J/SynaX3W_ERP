"""Pruebas del núcleo de seguridad del módulo ``users`` (Hito 2).

Cubre los contratos de ``specs/users_spec.md`` (sección 4) sin depender del
router HTTP del módulo (que se implementa en un hito posterior):

* Argon2id, política de contraseñas y verificación dummy;
* emisión/decodificación de JWT de acceso y refresco, expiraciones y
  rechazo de tokens manipulados o del tipo incorrecto;
* CAPTCHA aritmético firmado, con expiración y comparación en tiempo
  constante;
* dependencias FastAPI ``get_current_active_user`` y ``require_roles``,
  incluido el *bypass* de ``ADMINISTRATOR``.
"""

from __future__ import annotations

import os
import re
import sys
import uuid
from collections.abc import Generator
from datetime import timedelta
from pathlib import Path
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
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
    FORBIDDEN_DETAIL,
    INACTIVE_USER_DETAIL,
    CaptchaError,
    PasswordPolicyError,
    TokenError,
    create_access_token,
    create_refresh_token,
    create_token_pair,
    decode_access_token,
    decode_refresh_token,
    generate_captcha,
    get_current_active_user,
    hash_password,
    require_roles,
    validate_captcha,
    validate_password_strength,
    verify_dummy_password,
    verify_password,
)
from src.modules.users.models import Role, RoleEnum, User  # noqa: E402

_PASSWORD = "Valid1234!"
_HASHED_PASSWORD = hash_password(_PASSWORD)
_CAPTCHA_PATTERN = re.compile(r"^¿Cuánto es (\d+) \+ (\d+)\?$")


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture()
def db_engine() -> Generator[Engine, None, None]:
    """Engine SQLite en memoria compartido por todas las sesiones."""
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
    """App mínima que ejercita las dependencias de seguridad reales."""
    session_factory = sessionmaker(bind=db_engine, expire_on_commit=False)

    def _override_get_db() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db

    @app.get("/me")
    def me(
        user: Annotated[User, Depends(get_current_active_user)],
    ) -> dict[str, str]:
        return {"email": user.email, "role": user.role.name.value}

    @app.get("/sales")
    def sales(
        _user: Annotated[User, Depends(require_roles([RoleEnum.SALES]))],
    ) -> dict[str, bool]:
        return {"ok": True}

    @app.get("/inventory")
    def inventory(
        _user: Annotated[User, Depends(require_roles([RoleEnum.INVENTORY]))],
    ) -> dict[str, bool]:
        return {"ok": True}

    with TestClient(app) as client:
        yield client


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
    role_enum: RoleEnum,
    *,
    email: str,
    username: str,
    is_active: bool = True,
) -> User:
    user = User(
        email=email,
        username=username,
        full_name=username.replace("_", " ").title(),
        hashed_password=_HASHED_PASSWORD,
        role_id=_role(db, role_enum).id,
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _captcha_answer(question: str) -> int:
    match = _CAPTCHA_PATTERN.fullmatch(question)
    assert match is not None, question
    left, right = (int(value) for value in match.groups())
    assert 1 <= left <= 20
    assert 1 <= right <= 20
    return left + right


# --------------------------------------------------------------------------- #
# Contraseñas
# --------------------------------------------------------------------------- #


def test_hash_and_verify_password_uses_argon2id() -> None:
    hashed = hash_password(_PASSWORD)

    assert hashed.startswith("$argon2id$")
    assert verify_password(_PASSWORD, hashed) is True
    assert verify_password("Wrong1234!", hashed) is False
    assert verify_dummy_password() is None
    # Un hash corrupto no debe lanzar ni saltarse el coste de Argon2.
    assert verify_password(_PASSWORD, "not-a-valid-hash") is False


@pytest.mark.parametrize(
    "password",
    [
        "short",
        "alllowercase1!",
        "ALLUPPERCASE1!",
        "NoNumbers!!",
        "NoSpecial123",
        "Aa1!" + "a" * 130,
    ],
)
def test_password_policy_rejects_weak_or_oversized(password: str) -> None:
    with pytest.raises(PasswordPolicyError):
        validate_password_strength(password)


def test_password_policy_accepts_valid_and_hash_applies_it() -> None:
    assert validate_password_strength(_PASSWORD) == _PASSWORD

    with pytest.raises(PasswordPolicyError):
        hash_password("weak")


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #


def test_jwt_contract_and_default_expirations() -> None:
    subject = uuid.uuid4()
    pair = create_token_pair(subject)

    assert pair.token_type == "bearer"
    assert pair.expires_in == 30 * 60

    access = decode_access_token(pair.access_token)
    refresh = decode_refresh_token(pair.refresh_token)

    assert access["sub"] == str(subject)
    assert refresh["sub"] == str(subject)
    assert access["type"] == "access"
    assert refresh["type"] == "refresh"
    assert access["exp"] - access["iat"] == 30 * 60
    assert refresh["exp"] - refresh["iat"] == 7 * 24 * 60 * 60


def test_jwt_rejects_wrong_type_tampering_and_expired_tokens() -> None:
    subject = uuid.uuid4()
    access = create_access_token(subject)
    refresh = create_refresh_token(subject)
    expired = create_access_token(subject, expires_delta=timedelta(seconds=-5))

    for token, decoder in (
        (refresh, decode_access_token),
        (access, decode_refresh_token),
        (access + "x", decode_access_token),
        ("not-a-token", decode_access_token),
        ("", decode_access_token),
        (expired, decode_access_token),
    ):
        with pytest.raises(TokenError):
            decoder(token)


# --------------------------------------------------------------------------- #
# CAPTCHA
# --------------------------------------------------------------------------- #


def test_captcha_roundtrip_accepts_int_and_string_answers() -> None:
    challenge = generate_captcha()
    answer = _captcha_answer(challenge.question)

    validate_captcha(challenge.captcha_token, answer)
    validate_captcha(challenge.captcha_token, str(answer))


def test_captcha_rejects_wrong_tampered_and_non_integer_answers() -> None:
    challenge = generate_captcha()
    answer = _captcha_answer(challenge.question)

    for token, provided in (
        (challenge.captcha_token, answer + 1),
        (challenge.captcha_token + "x", answer),
        ("", answer),
        (challenge.captcha_token, "not-a-number"),
        (challenge.captcha_token, 19.5),
        (challenge.captcha_token, True),
    ):
        with pytest.raises(CaptchaError):
            validate_captcha(token, provided)


def test_captcha_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    challenge = generate_captcha()
    answer = _captcha_answer(challenge.question)
    monkeypatch.setattr(settings, "CAPTCHA_MAX_AGE_SECONDS", -1)

    with pytest.raises(CaptchaError):
        validate_captcha(challenge.captcha_token, answer)


# --------------------------------------------------------------------------- #
# Dependencias FastAPI
# --------------------------------------------------------------------------- #


def test_me_returns_authenticated_profile(api: TestClient, db_session: Session) -> None:
    user = _create_user(
        db_session,
        RoleEnum.SALES,
        email="sales@example.com",
        username="sales_user",
    )

    response = api.get("/me", headers=_auth(create_access_token(user.id)))

    assert response.status_code == 200
    assert response.json() == {"email": "sales@example.com", "role": "sales"}


def test_missing_invalid_or_unknown_user_tokens_are_401(api: TestClient) -> None:
    missing = api.get("/me")
    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"

    assert api.get("/me", headers=_auth("not-a-token")).status_code == 401
    assert api.get("/me", headers={"Authorization": "Basic abc"}).status_code == 401

    unknown_user_token = create_access_token(uuid.uuid4())
    assert api.get("/me", headers=_auth(unknown_user_token)).status_code == 401


def test_inactive_user_is_forbidden(
    api: TestClient, db_session: Session
) -> None:
    user = _create_user(
        db_session,
        RoleEnum.SALES,
        email="inactive@example.com",
        username="inactive_user",
        is_active=False,
    )

    response = api.get("/me", headers=_auth(create_access_token(user.id)))

    assert response.status_code == 403
    assert response.json()["detail"] == INACTIVE_USER_DETAIL


def test_role_matrix_and_administrator_bypass(
    api: TestClient, db_session: Session
) -> None:
    sales = _create_user(
        db_session,
        RoleEnum.SALES,
        email="sales2@example.com",
        username="sales_user_2",
    )
    inventory = _create_user(
        db_session,
        RoleEnum.INVENTORY,
        email="inventory@example.com",
        username="inventory_user",
    )
    administrator = _create_user(
        db_session,
        RoleEnum.ADMINISTRATOR,
        email="admin@example.com",
        username="administrator_user",
    )

    sales_token = create_access_token(sales.id)
    inventory_token = create_access_token(inventory.id)
    admin_token = create_access_token(administrator.id)

    assert api.get("/sales", headers=_auth(sales_token)).status_code == 200
    forbidden = api.get("/inventory", headers=_auth(sales_token))
    assert forbidden.status_code == 403
    assert forbidden.json()["detail"] == FORBIDDEN_DETAIL

    assert api.get("/sales", headers=_auth(inventory_token)).status_code == 403
    # ADMINISTRATOR pasa aunque no esté en la lista de roles permitidos.
    assert api.get("/sales", headers=_auth(admin_token)).status_code == 200
    assert api.get("/inventory", headers=_auth(admin_token)).status_code == 200


def test_refresh_token_is_rejected_as_access_token(
    api: TestClient, db_session: Session
) -> None:
    user = _create_user(
        db_session,
        RoleEnum.SALES,
        email="refresh@example.com",
        username="refresh_user",
    )

    response = api.get("/me", headers=_auth(create_refresh_token(user.id)))

    assert response.status_code == 401
