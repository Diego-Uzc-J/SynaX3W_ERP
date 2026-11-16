"""Pruebas de administración de usuarios y blindaje RBAC (Hito 4).

Cubre ``specs/users_spec.md`` (secciones 3.1, 4.3 y 5.2):

* endpoints ``/api/v1/users`` exclusivos de ``ADMINISTRATOR``;
* creación con ``role_id`` válido, contraseña Argon2id y unicidad;
* listado paginado con filtros seguros por rol/estado y búsqueda literal;
* actualización parcial de datos, rol y ``is_active``;
* restablecimiento administrativo de contraseña;
* rechazo de asignación masiva y de contraseñas débiles;
* matriz RBAC de ``inventory``: escritura para ``INVENTORY``, lectura para
  ``SALES``/``PURCHASING``/``MANUFACTURING``, denegación para ``ACCOUNTING`` y
  ``HR``, y bypass de ``ADMINISTRATOR``;
* un usuario desactivado pierde el acceso aunque su token siga vigente.
"""

from __future__ import annotations

import os
import sys
import uuid
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
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

from src.core.database import Base, get_db  # noqa: E402
from src.core.security import (  # noqa: E402
    FORBIDDEN_DETAIL,
    create_access_token,
    hash_password,
    verify_password,
)
from src.modules.inventory.router import (  # noqa: E402
    inventory_exception_handler,
    router as inventory_router,
)
from src.modules.inventory.services import InventoryError  # noqa: E402
from src.modules.users.models import Role, RoleEnum, User  # noqa: E402
from src.modules.users.router import (  # noqa: E402
    limiter,
    router as users_router,
    users_exception_handler,
)
from src.modules.users.services import UserServiceError  # noqa: E402

USERS_URL = "/api/v1/users/"
ROLES_URL = "/api/v1/users/roles"
PRODUCTS_URL = "/api/v1/inventory/products"
STOCK_URL = "/api/v1/inventory/stock"

_INITIAL_PASSWORD = "Initial1234!"
_INITIAL_HASH = hash_password(_INITIAL_PASSWORD)
_NEW_PASSWORD = "Reset12345!"

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
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture()
def db_engine() -> Generator[Engine, None, None]:
    """Engine SQLite en memoria compartido por la app y las aserciones."""
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
def api(db_session: Session) -> Generator[TestClient, None, None]:
    """App con los routers reales de ``users`` e ``inventory``."""

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_exception_handler(UserServiceError, users_exception_handler)
    app.add_exception_handler(InventoryError, inventory_exception_handler)
    app.include_router(users_router, prefix="/api/v1/users")
    app.include_router(inventory_router, prefix="/api/v1/inventory")
    app.dependency_overrides[get_db] = override_get_db

    limiter.reset()
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)
        limiter.reset()


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #


def _seed_roles(db: Session) -> dict[RoleEnum, Role]:
    """Crea el catálogo completo de roles si no existe."""
    for name, modules in _ROLE_MODULES.items():
        role = db.scalar(select(Role).where(Role.name == name))
        if role is None:
            db.add(
                Role(
                    name=name,
                    description=name.value,
                    allowed_modules=modules,
                )
            )
    db.commit()
    return {role.name: role for role in db.scalars(select(Role)).all()}


def _create_user(
    db: Session,
    role: Role,
    *,
    email: str,
    username: str,
    is_active: bool = True,
    failed_login_attempts: int = 0,
    locked_until: datetime | None = None,
) -> User:
    user = User(
        email=email,
        username=username,
        full_name=username.replace("_", " ").title(),
        hashed_password=_INITIAL_HASH,
        role_id=role.id,
        is_active=is_active,
        failed_login_attempts=failed_login_attempts,
        locked_until=locked_until,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def _product_payload(sku: str) -> dict[str, object]:
    return {
        "sku": sku,
        "name": f"Producto {sku}",
        "unit_price": "10.00",
        "minimum_stock": 1,
    }


# --------------------------------------------------------------------------- #
# Endpoints administrativos: guardia de rol
# --------------------------------------------------------------------------- #


def test_admin_endpoints_require_administrator(
    api: TestClient, db_session: Session
) -> None:
    roles = _seed_roles(db_session)
    sales = _create_user(
        db_session,
        roles[RoleEnum.SALES],
        email="sales@example.com",
        username="sales_user",
    )
    admin = _create_user(
        db_session,
        roles[RoleEnum.ADMINISTRATOR],
        email="admin@example.com",
        username="admin_user",
    )

    assert api.get(ROLES_URL).status_code == 401
    assert api.get(ROLES_URL, headers=_auth(sales)).status_code == 403
    assert api.get(ROLES_URL, headers=_auth(admin)).status_code == 200
    assert api.get(USERS_URL, headers=_auth(sales)).status_code == 403


def test_roles_endpoint_lists_catalog_and_modules(
    api: TestClient, db_session: Session
) -> None:
    roles = _seed_roles(db_session)
    admin = _create_user(
        db_session,
        roles[RoleEnum.ADMINISTRATOR],
        email="admin@example.com",
        username="admin_user",
    )

    response = api.get(ROLES_URL, headers=_auth(admin))

    assert response.status_code == 200, response.text
    body = response.json()
    assert {item["name"] for item in body} == {
        role.value for role in RoleEnum
    }
    sales = next(item for item in body if item["name"] == "sales")
    assert sales["allowed_modules"] == ["sales", "inventory:read"]
    assert "hashed_password" not in response.text


# --------------------------------------------------------------------------- #
# Creación
# --------------------------------------------------------------------------- #


def test_create_user_hashes_password_and_assigns_role(
    api: TestClient, db_session: Session
) -> None:
    roles = _seed_roles(db_session)
    admin = _create_user(
        db_session,
        roles[RoleEnum.ADMINISTRATOR],
        email="admin@example.com",
        username="admin_user",
    )

    response = api.post(
        USERS_URL,
        headers=_auth(admin),
        json={
            "email": "New.User@Example.COM",
            "username": "newuser",
            "full_name": "Nuevo Usuario",
            "password": _NEW_PASSWORD,
            "role_id": str(roles[RoleEnum.SALES].id),
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == "new.user@example.com"
    assert body["role"]["name"] == "sales"
    assert body["is_active"] is True
    assert "hashed_password" not in response.text

    created = db_session.scalar(
        select(User).where(User.email == "new.user@example.com")
    )
    assert created is not None
    assert verify_password(_NEW_PASSWORD, created.hashed_password)
    assert created.hashed_password != _NEW_PASSWORD


def test_create_user_rejects_invalid_role_and_duplicates(
    api: TestClient, db_session: Session
) -> None:
    roles = _seed_roles(db_session)
    admin = _create_user(
        db_session,
        roles[RoleEnum.ADMINISTRATOR],
        email="admin@example.com",
        username="admin_user",
    )
    existing = _create_user(
        db_session,
        roles[RoleEnum.SALES],
        email="existing@example.com",
        username="existing",
    )
    assert existing is not None

    invalid_role = api.post(
        USERS_URL,
        headers=_auth(admin),
        json={
            "email": "other@example.com",
            "username": "otheruser",
            "full_name": "Otro Usuario",
            "password": _NEW_PASSWORD,
            "role_id": str(uuid.uuid4()),
        },
    )
    assert invalid_role.status_code == 404
    assert invalid_role.json()["detail"] == "Rol no encontrado"

    duplicate_email = api.post(
        USERS_URL,
        headers=_auth(admin),
        json={
            "email": "EXISTING@example.com",
            "username": "different",
            "full_name": "Duplicado",
            "password": _NEW_PASSWORD,
            "role_id": str(roles[RoleEnum.SALES].id),
        },
    )
    assert duplicate_email.status_code == 409

    duplicate_username = api.post(
        USERS_URL,
        headers=_auth(admin),
        json={
            "email": "different@example.com",
            "username": "EXISTING",
            "full_name": "Duplicado",
            "password": _NEW_PASSWORD,
            "role_id": str(roles[RoleEnum.SALES].id),
        },
    )
    assert duplicate_username.status_code == 409


def test_create_user_rejects_mass_assignment_and_weak_password(
    api: TestClient, db_session: Session
) -> None:
    roles = _seed_roles(db_session)
    admin = _create_user(
        db_session,
        roles[RoleEnum.ADMINISTRATOR],
        email="admin@example.com",
        username="admin_user",
    )
    base_payload = {
        "email": "mass@example.com",
        "username": "massuser",
        "full_name": "Mass User",
        "password": _NEW_PASSWORD,
        "role_id": str(roles[RoleEnum.SALES].id),
    }

    injected = api.post(
        USERS_URL,
        headers=_auth(admin),
        json={**base_payload, "hashed_password": "injected"},
    )
    assert injected.status_code == 422

    weak = api.post(
        USERS_URL,
        headers=_auth(admin),
        json={**base_payload, "password": "weak"},
    )
    assert weak.status_code == 422


# --------------------------------------------------------------------------- #
# Listado y filtros
# --------------------------------------------------------------------------- #


def test_list_users_paginates_and_filters_by_role_and_state(
    api: TestClient, db_session: Session
) -> None:
    roles = _seed_roles(db_session)
    admin = _create_user(
        db_session,
        roles[RoleEnum.ADMINISTRATOR],
        email="admin@example.com",
        username="admin_user",
    )
    _create_user(
        db_session,
        roles[RoleEnum.SALES],
        email="sales1@example.com",
        username="sales_one",
    )
    _create_user(
        db_session,
        roles[RoleEnum.SALES],
        email="sales2@example.com",
        username="sales_two",
        is_active=False,
    )
    _create_user(
        db_session,
        roles[RoleEnum.INVENTORY],
        email="inventory@example.com",
        username="inventory_user",
    )

    active_sales = api.get(
        USERS_URL,
        headers=_auth(admin),
        params={"role": "sales", "is_active": True},
    )
    assert active_sales.status_code == 200, active_sales.text
    assert [item["username"] for item in active_sales.json()] == ["sales_one"]
    assert "hashed_password" not in active_sales.text

    inactive_sales = api.get(
        USERS_URL,
        headers=_auth(admin),
        params={"role": "sales", "is_active": False},
    )
    assert [item["username"] for item in inactive_sales.json()] == ["sales_two"]

    page = api.get(
        USERS_URL,
        headers=_auth(admin),
        params={"skip": 0, "limit": 1},
    )
    assert len(page.json()) == 1

    invalid_role = api.get(
        USERS_URL,
        headers=_auth(admin),
        params={"role": "not-a-role"},
    )
    assert invalid_role.status_code == 422


def test_list_users_search_is_parameterized_against_sql_injection(
    api: TestClient, db_session: Session
) -> None:
    roles = _seed_roles(db_session)
    admin = _create_user(
        db_session,
        roles[RoleEnum.ADMINISTRATOR],
        email="admin@example.com",
        username="admin_user",
    )
    _create_user(
        db_session,
        roles[RoleEnum.SALES],
        email="sales@example.com",
        username="sales_user",
    )

    response = api.get(
        USERS_URL,
        headers=_auth(admin),
        params={"search": "' OR '1'='1"},
    )

    assert response.status_code == 200, response.text
    # La cadena se trata como texto literal: no devuelve todas las filas.
    assert response.json() == []

    literal_wildcard = api.get(
        USERS_URL,
        headers=_auth(admin),
        params={"search": "%"},
    )
    assert literal_wildcard.status_code == 200
    assert literal_wildcard.json() == []


# --------------------------------------------------------------------------- #
# Actualización y restablecimiento
# --------------------------------------------------------------------------- #


def test_update_user_changes_data_role_and_status(
    api: TestClient, db_session: Session
) -> None:
    roles = _seed_roles(db_session)
    admin = _create_user(
        db_session,
        roles[RoleEnum.ADMINISTRATOR],
        email="admin@example.com",
        username="admin_user",
    )
    user = _create_user(
        db_session,
        roles[RoleEnum.SALES],
        email="sales@example.com",
        username="sales_user",
    )

    response = api.patch(
        f"{USERS_URL}{user.id}",
        headers=_auth(admin),
        json={
            "full_name": "Sales Actualizado",
            "role_id": str(roles[RoleEnum.INVENTORY].id),
            "is_active": False,
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["full_name"] == "Sales Actualizado"
    assert body["role"]["name"] == "inventory"
    assert body["is_active"] is False
    assert "hashed_password" not in response.text

    # El token emitido antes de la desactivación deja de servir (escenario 7).
    old_token = api.get(PRODUCTS_URL, headers=_auth(user))
    assert old_token.status_code == 403
    assert old_token.json()["detail"] == "Usuario inactivo"


def test_update_user_rejects_unknown_id_role_and_mass_assignment(
    api: TestClient, db_session: Session
) -> None:
    roles = _seed_roles(db_session)
    admin = _create_user(
        db_session,
        roles[RoleEnum.ADMINISTRATOR],
        email="admin@example.com",
        username="admin_user",
    )
    user = _create_user(
        db_session,
        roles[RoleEnum.SALES],
        email="sales@example.com",
        username="sales_user",
    )

    unknown = api.patch(
        f"{USERS_URL}{uuid.uuid4()}",
        headers=_auth(admin),
        json={"full_name": "Nadie"},
    )
    assert unknown.status_code == 404

    bad_role = api.patch(
        f"{USERS_URL}{user.id}",
        headers=_auth(admin),
        json={"role_id": str(uuid.uuid4())},
    )
    assert bad_role.status_code == 404

    mass_assignment = api.patch(
        f"{USERS_URL}{user.id}",
        headers=_auth(admin),
        json={"failed_login_attempts": 0},
    )
    assert mass_assignment.status_code == 422

    empty = api.patch(f"{USERS_URL}{user.id}", headers=_auth(admin), json={})
    assert empty.status_code == 422


def test_admin_password_reset_rehashes_and_clears_lockout(
    api: TestClient, db_session: Session
) -> None:
    roles = _seed_roles(db_session)
    admin = _create_user(
        db_session,
        roles[RoleEnum.ADMINISTRATOR],
        email="admin@example.com",
        username="admin_user",
    )
    user = _create_user(
        db_session,
        roles[RoleEnum.SALES],
        email="sales@example.com",
        username="sales_user",
        failed_login_attempts=4,
        locked_until=datetime.now(timezone.utc) + timedelta(minutes=10),
    )

    response = api.patch(
        f"{USERS_URL}{user.id}/password",
        headers=_auth(admin),
        json={"new_password": _NEW_PASSWORD},
    )

    assert response.status_code == 200, response.text
    assert "hashed_password" not in response.text

    db_session.refresh(user)
    assert verify_password(_NEW_PASSWORD, user.hashed_password)
    assert not verify_password(_INITIAL_PASSWORD, user.hashed_password)
    assert user.failed_login_attempts == 0
    assert user.locked_until is None

    unknown = api.patch(
        f"{USERS_URL}{uuid.uuid4()}/password",
        headers=_auth(admin),
        json={"new_password": _NEW_PASSWORD},
    )
    assert unknown.status_code == 404

    weak = api.patch(
        f"{USERS_URL}{user.id}/password",
        headers=_auth(admin),
        json={"new_password": "weak"},
    )
    assert weak.status_code == 422


def test_non_admin_cannot_create_update_or_reset_passwords(
    api: TestClient, db_session: Session
) -> None:
    roles = _seed_roles(db_session)
    inventory = _create_user(
        db_session,
        roles[RoleEnum.INVENTORY],
        email="inventory@example.com",
        username="inventory_user",
    )
    target = _create_user(
        db_session,
        roles[RoleEnum.SALES],
        email="sales@example.com",
        username="sales_user",
    )
    headers = _auth(inventory)

    create = api.post(
        USERS_URL,
        headers=headers,
        json={
            "email": "blocked@example.com",
            "username": "blocked",
            "full_name": "Blocked",
            "password": _NEW_PASSWORD,
            "role_id": str(roles[RoleEnum.SALES].id),
        },
    )
    update = api.patch(
        f"{USERS_URL}{target.id}",
        headers=headers,
        json={"is_active": False},
    )
    reset = api.patch(
        f"{USERS_URL}{target.id}/password",
        headers=headers,
        json={"new_password": _NEW_PASSWORD},
    )

    assert create.status_code == 403
    assert update.status_code == 403
    assert reset.status_code == 403


# --------------------------------------------------------------------------- #
# Matriz RBAC sobre inventory
# --------------------------------------------------------------------------- #


def test_inventory_rbac_matrix(api: TestClient, db_session: Session) -> None:
    roles = _seed_roles(db_session)
    users = {
        role: _create_user(
            db_session,
            roles[role],
            email=f"{role.value}@example.com",
            username=f"{role.value}_user",
        )
        for role in RoleEnum
    }
    headers = {role: _auth(user) for role, user in users.items()}

    # ADMINISTRATOR: bypass total, escritura incluida.
    admin_create = api.post(
        PRODUCTS_URL,
        headers=headers[RoleEnum.ADMINISTRATOR],
        json=_product_payload("RBAC-ADMIN-001"),
    )
    assert admin_create.status_code == 201, admin_create.text

    # INVENTORY: escritura y lectura.
    inventory_create = api.post(
        PRODUCTS_URL,
        headers=headers[RoleEnum.INVENTORY],
        json=_product_payload("RBAC-INV-001"),
    )
    assert inventory_create.status_code == 201, inventory_create.text
    assert (
        api.get(PRODUCTS_URL, headers=headers[RoleEnum.INVENTORY]).status_code
        == 200
    )

    # SALES: lectura de catálogo/stock, sin escritura.
    assert (
        api.get(PRODUCTS_URL, headers=headers[RoleEnum.SALES]).status_code
        == 200
    )
    assert api.get(STOCK_URL, headers=headers[RoleEnum.SALES]).status_code == 200
    sales_create = api.post(
        PRODUCTS_URL,
        headers=headers[RoleEnum.SALES],
        json=_product_payload("RBAC-SALES-001"),
    )
    assert sales_create.status_code == 403

    # PURCHASING y MANUFACTURING: solo lectura de inventario.
    for role in (RoleEnum.PURCHASING, RoleEnum.MANUFACTURING):
        assert api.get(PRODUCTS_URL, headers=headers[role]).status_code == 200
        denied = api.post(
            PRODUCTS_URL,
            headers=headers[role],
            json=_product_payload(f"RBAC-{role.value.upper()}-001"),
        )
        assert denied.status_code == 403

    # ACCOUNTING y HR no incluyen inventario en su matriz.
    for role in (RoleEnum.ACCOUNTING, RoleEnum.HR):
        denied = api.get(PRODUCTS_URL, headers=headers[role])
        assert denied.status_code == 403
        assert denied.json()["detail"] == FORBIDDEN_DETAIL

    # Sin token: no autenticado.
    assert api.get(PRODUCTS_URL).status_code == 401


def test_inventory_write_requires_inventory_role_for_warehouses_and_movements(
    api: TestClient, db_session: Session
) -> None:
    roles = _seed_roles(db_session)
    sales = _create_user(
        db_session,
        roles[RoleEnum.SALES],
        email="sales@example.com",
        username="sales_user",
    )
    inventory = _create_user(
        db_session,
        roles[RoleEnum.INVENTORY],
        email="inventory@example.com",
        username="inventory_user",
    )

    sales_warehouse = api.post(
        "/api/v1/inventory/warehouses",
        headers=_auth(sales),
        json={"code": "RBAC-WH-01", "name": "Bodega RBAC"},
    )
    assert sales_warehouse.status_code == 403

    inventory_warehouse = api.post(
        "/api/v1/inventory/warehouses",
        headers=_auth(inventory),
        json={"code": "RBAC-WH-01", "name": "Bodega RBAC"},
    )
    assert inventory_warehouse.status_code == 201, inventory_warehouse.text

    sales_movement = api.post(
        "/api/v1/inventory/movements",
        headers=_auth(sales),
        json={
            "product_id": 1,
            "movement_type": "INBOUND",
            "quantity": 1,
            "warehouse_destination_id": inventory_warehouse.json()["id"],
        },
    )
    assert sales_movement.status_code == 403
