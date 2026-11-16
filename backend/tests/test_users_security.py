"""Pruebas de seguridad Top OWASP del módulo ``users`` (Hito 5).

Implementa los siete escenarios de ``specs/users_spec.md`` (sección 6) con
``pytest`` y ``httpx.AsyncClient`` sobre una app FastAPI que incluye los
routers reales de ``users`` e ``inventory``.

Nota sobre el escenario 3: el módulo ``sales`` todavía no existe en
``backend/src/modules``. Para validar la matriz de aislamiento sin añadir
código de producción ficticio, la app de pruebas registra un endpoint de
sondeo ``GET /api/v1/sales/orders`` protegido con la misma dependencia real
``require_roles([RoleEnum.SALES])``. El resto de endpoints son los de
producción.
"""

from __future__ import annotations

import os
import re
import sys
import uuid
from collections.abc import AsyncIterator, Generator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi import APIRouter, Depends, FastAPI
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import create_engine, func, select
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
    CAPTCHA_INVALID_DETAIL,
    FORBIDDEN_DETAIL,
    INACTIVE_USER_DETAIL,
    INVALID_CREDENTIALS_DETAIL,
    create_access_token,
    decode_access_token,
    decode_refresh_token,
    hash_password,
    require_roles,
)
from src.modules.inventory.router import (  # noqa: E402
    inventory_exception_handler,
    router as inventory_router,
)
from src.modules.inventory.services import InventoryError  # noqa: E402
from src.modules.users import services  # noqa: E402
from src.modules.users.models import Role, RoleEnum, User  # noqa: E402
from src.modules.users.router import (  # noqa: E402
    limiter,
    router as users_router,
    users_exception_handler,
)
from src.modules.users.services import UserServiceError  # noqa: E402

pytestmark = pytest.mark.anyio

CAPTCHA_URL = "/api/v1/users/auth/captcha"
LOGIN_URL = "/api/v1/users/auth/login"
ME_URL = "/api/v1/users/auth/me"
USERS_URL = "/api/v1/users/"
ROLES_URL = "/api/v1/users/roles"
PRODUCTS_URL = "/api/v1/inventory/products"
SALES_ORDERS_URL = "/api/v1/sales/orders"

_PASSWORD = "Security1234!"
_HASHED_PASSWORD = hash_password(_PASSWORD)
_CAPTCHA_PATTERN = re.compile(r"^¿Cuánto es (\d+) \+ (\d+)\?$")

_ROLE_MODULES: dict[RoleEnum, list[str]] = {
    RoleEnum.ADMINISTRATOR: [
        "users",
        "inventory",
        "sales",
        "purchasing",
        "accounting",
        "hr",
        "manufacturing",
    ],
    RoleEnum.INVENTORY: ["inventory"],
    RoleEnum.SALES: ["sales", "inventory:read"],
    RoleEnum.PURCHASING: ["purchasing", "inventory:read"],
    RoleEnum.ACCOUNTING: ["accounting", "sales:read", "purchasing:read"],
    RoleEnum.HR: ["hr"],
    RoleEnum.MANUFACTURING: ["manufacturing", "inventory:read"],
}


# --------------------------------------------------------------------------- #
# Endpoint de sondeo para el futuro módulo sales (solo en pruebas)
# --------------------------------------------------------------------------- #

sales_probe_router = APIRouter(
    prefix="/api/v1/sales",
    tags=["test: sales probe"],
)


@sales_probe_router.get(
    "/orders",
    dependencies=[Depends(require_roles([RoleEnum.SALES]))],
)
def _sales_orders_probe() -> dict[str, list[dict]]:
    """Simula el guardia que tendrá ``sales`` cuando se implemente."""
    return {"orders": []}


# --------------------------------------------------------------------------- #
# Datos y fixtures
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class SeededUser:
    """Instantánea mínima de un usuario sembrado."""

    id: uuid.UUID
    email: str
    username: str
    role_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class SeedData:
    """Roles y usuarios compartidos por los escenarios."""

    roles: dict[RoleEnum, uuid.UUID]
    users: dict[RoleEnum, SeededUser]


@pytest.fixture()
def anyio_backend() -> str:
    """Fuerza el backend asyncio; trio no forma parte del stack del ERP."""
    return "asyncio"


@pytest.fixture()
def db_engine() -> Generator[Engine, None, None]:
    """Engine SQLite en memoria aislado por prueba."""
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
def session_factory(
    db_engine: Engine,
) -> sessionmaker[Session]:
    """Fábrica de sesiones usada por la app y por las aserciones."""
    return sessionmaker(bind=db_engine, expire_on_commit=False)


@pytest.fixture()
def seed(session_factory: sessionmaker[Session]) -> SeedData:
    """Siembra los siete roles y un usuario por rol relevante."""
    with session_factory() as db:
        role_ids: dict[RoleEnum, uuid.UUID] = {}
        for role_enum in RoleEnum:
            role = db.scalar(
                select(Role).where(Role.name == role_enum)
            )
            if role is None:
                role = Role(
                    name=role_enum,
                    description=role_enum.value,
                    allowed_modules=_ROLE_MODULES[role_enum],
                )
                db.add(role)
                db.flush()
            role_ids[role_enum] = role.id

        users: dict[RoleEnum, SeededUser] = {}
        for role_enum in (
            RoleEnum.ADMINISTRATOR,
            RoleEnum.INVENTORY,
            RoleEnum.SALES,
        ):
            user = User(
                email=f"{role_enum.value}@security.synapsisx.com",
                username=f"{role_enum.value}_security",
                full_name=f"{role_enum.value.title()} Security",
                hashed_password=_HASHED_PASSWORD,
                role_id=role_ids[role_enum],
                is_active=True,
            )
            db.add(user)
            db.flush()
            users[role_enum] = SeededUser(
                id=user.id,
                email=user.email,
                username=user.username,
                role_id=role_ids[role_enum],
            )

        db.commit()

    return SeedData(roles=role_ids, users=users)


@pytest.fixture()
def app(session_factory: sessionmaker[Session]) -> FastAPI:
    """App con los routers reales y ``get_db`` apuntando a SQLite."""

    def override_get_db() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    application = FastAPI()
    application.state.limiter = limiter
    application.add_exception_handler(
        RateLimitExceeded, _rate_limit_exceeded_handler
    )
    application.add_exception_handler(
        UserServiceError, users_exception_handler
    )
    application.add_exception_handler(
        InventoryError, inventory_exception_handler
    )
    application.include_router(users_router, prefix="/api/v1/users")
    application.include_router(
        inventory_router, prefix="/api/v1/inventory"
    )
    application.include_router(sales_probe_router)
    application.dependency_overrides[get_db] = override_get_db
    return application


@pytest.fixture()
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Cliente HTTP asíncrono contra la app ASGI."""
    limiter.reset()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        timeout=30.0,
    ) as async_client:
        yield async_client
    limiter.reset()


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #


def _auth(user: SeededUser) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def _captcha(
    client: httpx.AsyncClient,
) -> tuple[dict[str, str], int]:
    """Obtiene un desafío y calcula la suma esperada."""
    response = await client.get(CAPTCHA_URL)
    assert response.status_code == 200, response.text
    body = response.json()
    match = _CAPTCHA_PATTERN.fullmatch(body["question"])
    assert match is not None, body["question"]
    left, right = (int(value) for value in match.groups())
    return body, left + right


async def _login(
    client: httpx.AsyncClient,
    *,
    identifier: str,
    password: str = _PASSWORD,
    challenge: tuple[dict[str, str], int] | None = None,
    answer_delta: int = 0,
) -> httpx.Response:
    """Envía un login resolviendo (o reutilizando) un CAPTCHA."""
    body, answer = challenge or await _captcha(client)
    return await client.post(
        LOGIN_URL,
        json={
            "identifier": identifier,
            "password": password,
            "captcha_token": body["captcha_token"],
            "captcha_answer": answer + answer_delta,
        },
    )


def _assert_no_sensitive_data(response: httpx.Response) -> None:
    """Comprueba que la respuesta no expone hash ni contraseñas."""
    text = response.text
    assert "hashed_password" not in text
    assert "$argon2id$" not in text
    assert _PASSWORD not in text


# --------------------------------------------------------------------------- #
# Escenario 1: login exitoso con CAPTCHA aritmético
# --------------------------------------------------------------------------- #


async def test_scenario_1_login_with_valid_arithmetic_captcha(
    client: httpx.AsyncClient,
    seed: SeedData,
) -> None:
    user = seed.users[RoleEnum.SALES]

    response = await _login(client, identifier=user.email)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["role"] == "sales"
    assert body["allowed_modules"] == ["sales", "inventory:read"]
    assert body["access_token"]
    assert body["refresh_token"]
    _assert_no_sensitive_data(response)

    access = decode_access_token(body["access_token"])
    refresh = decode_refresh_token(body["refresh_token"])
    assert access["sub"] == str(user.id)
    assert refresh["sub"] == str(user.id)
    assert access["type"] == "access"
    assert refresh["type"] == "refresh"


# --------------------------------------------------------------------------- #
# Escenario 2: CAPTCHA incorrecto, manipulado o expirado
# --------------------------------------------------------------------------- #


async def test_scenario_2_rejects_wrong_tampered_and_expired_captcha(
    client: httpx.AsyncClient,
    seed: SeedData,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = seed.users[RoleEnum.SALES]

    wrong = await _login(client, identifier=user.email, answer_delta=1)
    assert wrong.status_code == 400
    assert wrong.json()["detail"] == CAPTCHA_INVALID_DETAIL
    assert "access_token" not in wrong.text

    challenge, answer = await _captcha(client)
    tampered = await client.post(
        LOGIN_URL,
        json={
            "identifier": user.email,
            "password": _PASSWORD,
            "captcha_token": challenge["captcha_token"] + "x",
            "captcha_answer": answer,
        },
    )
    assert tampered.status_code == 400
    assert tampered.json()["detail"] == CAPTCHA_INVALID_DETAIL

    challenge, answer = await _captcha(client)
    monkeypatch.setattr(settings, "CAPTCHA_MAX_AGE_SECONDS", -1)
    expired = await _login(
        client,
        identifier=user.email,
        challenge=(challenge, answer),
    )
    assert expired.status_code == 400
    assert expired.json()["detail"] == CAPTCHA_INVALID_DETAIL
    assert "access_token" not in expired.text

    # Un CAPTCHA rechazado nunca incrementa los intentos fallidos.
    with session_factory() as db:
        persisted = db.get(User, user.id)
        assert persisted is not None
        assert persisted.failed_login_attempts == 0
        assert persisted.locked_until is None


# --------------------------------------------------------------------------- #
# Escenario 3: control de acceso horizontal y vertical
# --------------------------------------------------------------------------- #


async def test_scenario_3_cross_module_access_control(
    client: httpx.AsyncClient,
    seed: SeedData,
) -> None:
    inventory_headers = _auth(seed.users[RoleEnum.INVENTORY])
    admin_headers = _auth(seed.users[RoleEnum.ADMINISTRATOR])
    sales_headers = _auth(seed.users[RoleEnum.SALES])

    # Acceso legítimo a su propio módulo.
    own_module = await client.get(PRODUCTS_URL, headers=inventory_headers)
    assert own_module.status_code == 200

    # Horizontal: INVENTORY no puede entrar en sales.
    sales_denied = await client.get(
        SALES_ORDERS_URL, headers=inventory_headers
    )
    assert sales_denied.status_code == 403
    assert sales_denied.json()["detail"] == FORBIDDEN_DETAIL

    # Vertical: INVENTORY no puede administrar usuarios.
    users_denied = await client.get(USERS_URL, headers=inventory_headers)
    assert users_denied.status_code == 403
    assert users_denied.json()["detail"] == FORBIDDEN_DETAIL

    # ADMINISTRATOR obtiene 200 en ambos módulos (bypass).
    assert (
        await client.get(SALES_ORDERS_URL, headers=admin_headers)
    ).status_code == 200
    assert (
        await client.get(USERS_URL, headers=admin_headers)
    ).status_code == 200

    # El rol propietario de sales sí accede a su módulo, pero no a users.
    assert (
        await client.get(SALES_ORDERS_URL, headers=sales_headers)
    ).status_code == 200
    assert (
        await client.get(USERS_URL, headers=sales_headers)
    ).status_code == 403


# --------------------------------------------------------------------------- #
# Escenario 4: fuerza bruta y protección contra timing attacks
# --------------------------------------------------------------------------- #


async def test_scenario_4_account_locks_after_five_failed_attempts(
    client: httpx.AsyncClient,
    seed: SeedData,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # El límite de 5/min impediría llegar al sexto intento.
    monkeypatch.setattr(limiter, "enabled", False)
    user = seed.users[RoleEnum.SALES]

    for _ in range(5):
        response = await _login(
            client,
            identifier=user.email,
            password="Wrong1234!",
        )
        assert response.status_code == 401
        assert response.json()["detail"] == INVALID_CREDENTIALS_DETAIL

    with session_factory() as db:
        persisted = db.get(User, user.id)
        assert persisted is not None
        assert persisted.locked_until is not None
        remaining = _as_utc(persisted.locked_until) - datetime.now(
            timezone.utc
        )
        assert timedelta(minutes=14) < remaining <= timedelta(minutes=15)

    # Incluso con la contraseña correcta, el bloqueo impide emitir tokens.
    sixth = await _login(client, identifier=user.email)
    assert sixth.status_code in {401, 423}
    assert "access_token" not in sixth.text


async def test_scenario_4_unknown_user_runs_dummy_hash(
    client: httpx.AsyncClient,
    seed: SeedData,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El usuario inexistente ejecuta Argon2id dummy (anti-timing)."""
    monkeypatch.setattr(limiter, "enabled", False)
    dummy_calls: list[None] = []
    monkeypatch.setattr(
        services,
        "verify_dummy_password",
        lambda: dummy_calls.append(None),
    )

    unknown = await _login(
        client, identifier="ghost@security.synapsisx.com"
    )
    assert unknown.status_code == 401
    assert unknown.json()["detail"] == INVALID_CREDENTIALS_DETAIL
    assert len(dummy_calls) == 1

    # Una contraseña incorrecta de un usuario real no ejecuta el hash dummy.
    wrong = await _login(
        client,
        identifier=seed.users[RoleEnum.SALES].email,
        password="Wrong1234!",
    )
    assert wrong.status_code == 401
    assert len(dummy_calls) == 1


# --------------------------------------------------------------------------- #
# Escenario 5: asignación masiva de campos privilegiados
# --------------------------------------------------------------------------- #


async def test_scenario_5_rejects_mass_assignment(
    client: httpx.AsyncClient,
    seed: SeedData,
    session_factory: sessionmaker[Session],
) -> None:
    admin_headers = _auth(seed.users[RoleEnum.ADMINISTRATOR])
    base_payload = {
        "email": "mass@security.synapsisx.com",
        "username": "mass_security",
        "full_name": "Mass Security",
        "password": _PASSWORD,
        "role_id": str(seed.roles[RoleEnum.SALES]),
    }

    for extra in (
        {"role": "administrator"},
        {"is_active": True},
        {"failed_login_attempts": 0},
        {"hashed_password": "injected"},
        {"locked_until": "2099-01-01T00:00:00Z"},
    ):
        response = await client.post(
            USERS_URL,
            headers=admin_headers,
            json={**base_payload, **extra},
        )
        assert response.status_code == 422, response.text

    target = seed.users[RoleEnum.SALES]
    patch = await client.patch(
        f"{USERS_URL}{target.id}",
        headers=admin_headers,
        json={
            "role": "administrator",
            "is_active": True,
            "failed_login_attempts": 0,
        },
    )
    assert patch.status_code == 422

    # Ningún intento de asignación masiva alteró el estado ni creó usuarios.
    with session_factory() as db:
        persisted = db.get(User, target.id)
        assert persisted is not None
        assert persisted.role_id == target.role_id
        assert persisted.failed_login_attempts == 0
        assert (
            db.scalar(
                select(func.count())
                .select_from(User)
                .where(User.email == "mass@security.synapsisx.com")
            )
            == 0
        )


# --------------------------------------------------------------------------- #
# Escenario 6: inyección SQL y exposición de datos sensibles
# --------------------------------------------------------------------------- #


async def test_scenario_6_sql_injection_and_sensitive_data_exposure(
    client: httpx.AsyncClient,
    seed: SeedData,
    session_factory: sessionmaker[Session],
) -> None:
    admin_headers = _auth(seed.users[RoleEnum.ADMINISTRATOR])

    with session_factory() as db:
        before = db.scalar(select(func.count()).select_from(User))

    injected = await client.get(
        USERS_URL,
        headers=admin_headers,
        params={"search": "' OR '1'='1"},
    )
    assert injected.status_code == 200, injected.text
    # El texto se liga como parámetro: no devuelve todas las filas.
    assert injected.json() == []
    _assert_no_sensitive_data(injected)

    wildcard = await client.get(
        USERS_URL,
        headers=admin_headers,
        params={"search": "%"},
    )
    assert wildcard.status_code == 200
    assert wildcard.json() == []

    with session_factory() as db:
        after = db.scalar(select(func.count()).select_from(User))
    assert after == before

    listing = await client.get(USERS_URL, headers=admin_headers)
    assert listing.status_code == 200
    _assert_no_sensitive_data(listing)

    roles = await client.get(ROLES_URL, headers=admin_headers)
    assert roles.status_code == 200
    _assert_no_sensitive_data(roles)

    login = await _login(
        client, identifier=seed.users[RoleEnum.SALES].email
    )
    assert login.status_code == 200
    _assert_no_sensitive_data(login)

    profile = await client.get(
        ME_URL, headers=_auth(seed.users[RoleEnum.SALES])
    )
    assert profile.status_code == 200
    _assert_no_sensitive_data(profile)


# --------------------------------------------------------------------------- #
# Escenario 7: invalidación de acceso para usuario desactivado
# --------------------------------------------------------------------------- #


async def test_scenario_7_deactivated_user_token_is_rejected(
    client: httpx.AsyncClient,
    seed: SeedData,
) -> None:
    sales = seed.users[RoleEnum.SALES]
    sales_headers = _auth(sales)
    admin_headers = _auth(seed.users[RoleEnum.ADMINISTRATOR])

    # El token es válido y el rol SALES puede leer inventario.
    before = await client.get(PRODUCTS_URL, headers=sales_headers)
    assert before.status_code == 200

    deactivated = await client.patch(
        f"{USERS_URL}{sales.id}",
        headers=admin_headers,
        json={"is_active": False},
    )
    assert deactivated.status_code == 200, deactivated.text
    assert deactivated.json()["is_active"] is False

    # El mismo token deja de servir de inmediato en cualquier endpoint.
    denied = await client.get(PRODUCTS_URL, headers=sales_headers)
    assert denied.status_code == 403
    assert denied.json()["detail"] == INACTIVE_USER_DETAIL

    profile = await client.get(ME_URL, headers=sales_headers)
    assert profile.status_code == 403
    assert profile.json()["detail"] == INACTIVE_USER_DETAIL

    # El administrador conserva el acceso.
    assert (
        await client.get(USERS_URL, headers=admin_headers)
    ).status_code == 200
