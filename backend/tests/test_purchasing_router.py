"""Pruebas HTTP y RBAC del router del módulo de Compras (``purchasing``).

Verifica los contratos de ``specs/purchasing_spec.md`` (sección 4) a través de
la API real (``TestClient``): ciclo proveedor → OC → recepción → factura →
abonos, con los guardias de la matriz RBAC de ``specs/users_spec.md``:

* 401 sin token o con token inválido;
* 403 para un usuario con rol sin permiso ``purchasing``;
* 200/201 para los roles ``PURCHASING`` y ``ADMINISTRATOR`` (bypass).

Se usa SQLite en memoria con el mismo engine de las pruebas de `sales` para no
depender de PostgreSQL. El ``get_db`` de la aplicación se sustituye por una
sesión compartida con las aserciones.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Generator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ["DATABASE_URL"] = "sqlite://"

from src.core.database import Base, get_db  # noqa: E402
from src.core.security import create_access_token, hash_password  # noqa: E402
from src.main import app  # noqa: E402
from src.modules.purchasing.models import SupplierBillStatus  # noqa: E402
from src.modules.users.models import Role, RoleEnum, User  # noqa: E402

PURCHASING_URL = "/api/v1/purchasing"
INVENTORY_URL = "/api/v1/inventory"

_HASHED_PASSWORD = hash_password("Purchasing1234!")
_TODAY = date.today()


# --------------------------------------------------------------------------- #
# Fixtures de base de datos, API y usuarios
# --------------------------------------------------------------------------- #


@pytest.fixture()
def db_engine() -> Generator[Engine, None, None]:
    """Engine SQLite aislado por prueba, sin ``BEGIN`` implícito de pysqlite."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _disable_implicit_begin(
        dbapi_connection: Any, _connection_record: Any
    ) -> None:
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _emit_begin(connection: Any) -> None:
        connection.exec_driver_sql("BEGIN")

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
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """Cliente HTTP con la sesión de prueba inyectada en ``get_db``."""

    def override_get_db() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)


def _role(db_session: Session, name: RoleEnum, modules: list[str]) -> Role:
    role = db_session.scalar(select(Role).where(Role.name == name))
    if role is None:
        role = Role(name=name, description=name.value, allowed_modules=modules)
        db_session.add(role)
        db_session.flush()
    return role


def _user(
    db_session: Session, *, role: Role, username: str, email: str
) -> User:
    user = User(
        email=email,
        username=username,
        full_name=username.title(),
        hashed_password=_HASHED_PASSWORD,
        role_id=role.id,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def accounts(db_session: Session) -> dict[str, User]:
    admin_role = _role(db_session, RoleEnum.ADMINISTRATOR, ["*"])
    purchasing_role = _role(
        db_session, RoleEnum.PURCHASING, ["purchasing", "inventory:read"]
    )
    inventory_role = _role(
        db_session, RoleEnum.INVENTORY, ["inventory", "catalog:read"]
    )
    db_session.commit()

    return {
        "admin": _user(
            db_session,
            role=admin_role,
            username="compras_admin",
            email="compras-admin@example.com",
        ),
        "purchasing": _user(
            db_session,
            role=purchasing_role,
            username="comprador",
            email="comprador@example.com",
        ),
        "inventory": _user(
            db_session,
            role=inventory_role,
            username="bodeguero",
            email="bodeguero@example.com",
        ),
    }


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.fixture()
def admin_headers(accounts: dict[str, User]) -> dict[str, str]:
    return _headers(accounts["admin"])


@pytest.fixture()
def purchasing_headers(accounts: dict[str, User]) -> dict[str, str]:
    return _headers(accounts["purchasing"])


@pytest.fixture()
def inventory_headers(accounts: dict[str, User]) -> dict[str, str]:
    return _headers(accounts["inventory"])


# --------------------------------------------------------------------------- #
# Helpers de documento
# --------------------------------------------------------------------------- #


def _create_catalog(
    client: TestClient, admin_headers: dict[str, str]
) -> dict[str, int]:
    warehouse = client.post(
        f"{INVENTORY_URL}/warehouses",
        headers=admin_headers,
        json={"code": "BOD-COMpras", "name": "Bodega de compras"},
    )
    assert warehouse.status_code == 201, warehouse.text
    product = client.post(
        f"{INVENTORY_URL}/products",
        headers=admin_headers,
        json={
            "sku": "MAT-001",
            "name": "Materia prima",
            "unit_price": "100.00",
            "minimum_stock": 1,
        },
    )
    assert product.status_code == 201, product.text
    return {"warehouse_id": warehouse.json()["id"], "product_id": product.json()["id"]}


def _create_supplier(
    client: TestClient, headers: dict[str, str], *, tax_id: str = "800987654-3"
) -> int:
    response = client.post(
        f"{PURCHASING_URL}/suppliers",
        headers=headers,
        json={
            "tax_id": tax_id,
            "company_name": "Aceros del Norte S.A.S.",
            "contact_name": "María Gómez",
            "email": "ventas@acerosnorte.com",
            "address": "Calle 10 # 20-30",
            "payment_terms_days": 30,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_received_order(
    client: TestClient,
    headers: dict[str, str],
    *,
    supplier_id: int,
    product_id: int,
    warehouse_id: int,
    quantity: int = 10,
) -> dict[str, Any]:
    order = client.post(
        f"{PURCHASING_URL}/orders",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "expected_delivery_date": str(_TODAY + timedelta(days=5)),
            "items": [
                {
                    "product_id": product_id,
                    "quantity": quantity,
                    "unit_price": "100.00",
                    "tax_rate": "19.00",
                }
            ],
        },
    )
    assert order.status_code == 201, order.text
    order_data = order.json()

    approve = client.post(
        f"{PURCHASING_URL}/orders/{order_data['id']}/approve", headers=headers
    )
    assert approve.status_code == 200, approve.text

    receipt = client.post(
        f"{PURCHASING_URL}/receipts",
        headers=headers,
        json={
            "purchase_order_id": order_data["id"],
            "warehouse_id": warehouse_id,
            "items": [
                {
                    "purchase_order_item_id": order_data["items"][0]["id"],
                    "quantity": quantity,
                }
            ],
        },
    )
    assert receipt.status_code == 201, receipt.text
    return {"order": order_data, "receipt": receipt.json()}


def _create_bill(
    client: TestClient,
    headers: dict[str, str],
    *,
    supplier_id: int,
    received: dict[str, Any],
    invoice_number: str = "F-2026-0001",
) -> dict[str, Any]:
    response = client.post(
        f"{PURCHASING_URL}/bills",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "purchase_order_id": received["order"]["id"],
            "goods_receipt_id": received["receipt"]["id"],
            "supplier_invoice_number": invoice_number,
            "issue_date": str(_TODAY),
            "subtotal": "1000.00",
            "tax_amount": "190.00",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------------- #
# RBAC: autenticación y autorización
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "path",
    [
        "/suppliers",
        "/orders",
        "/receipts",
        "/bills",
    ],
)
def test_anonymous_request_is_rejected(client: TestClient, path: str) -> None:
    """Sin token, cualquier recurso de compras responde 401."""
    response = client.get(f"{PURCHASING_URL}{path}")
    assert response.status_code == 401


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/suppliers"),
        ("POST", "/suppliers"),
        ("GET", "/orders"),
        ("PATCH", "/orders/1"),
        ("GET", "/receipts"),
        ("POST", "/receipts"),
        ("GET", "/bills"),
        ("POST", "/bills"),
        ("POST", "/bills/1/pay"),
        ("GET", "/bills/1/payments"),
    ],
)
def test_role_without_purchasing_permission_is_forbidden(
    client: TestClient,
    inventory_headers: dict[str, str],
    method: str,
    path: str,
) -> None:
    """El rol ``INVENTORY`` no puede acceder a ningún endpoint de compras."""
    response = client.request(
        method, f"{PURCHASING_URL}{path}", headers=inventory_headers, json={}
    )
    assert response.status_code == 403


@pytest.mark.parametrize("headers_name", ["purchasing_headers", "admin_headers"])
def test_authorized_roles_can_list_resources(
    request: pytest.FixtureRequest,
    client: TestClient,
    headers_name: str,
) -> None:
    """``PURCHASING`` y ``ADMINISTRATOR`` pueden consultar los cuatro recursos."""
    headers: dict[str, str] = request.getfixturevalue(headers_name)
    for path in ("/suppliers", "/orders", "/receipts", "/bills"):
        response = client.get(f"{PURCHASING_URL}{path}", headers=headers)
        assert response.status_code == 200, response.text


@pytest.mark.parametrize("headers_name", ["purchasing_headers", "admin_headers"])
def test_authorized_roles_can_register_supplier(
    request: pytest.FixtureRequest,
    client: TestClient,
    headers_name: str,
) -> None:
    """Ambos roles autorizados registran proveedores (201)."""
    headers: dict[str, str] = request.getfixturevalue(headers_name)
    supplier_id = _create_supplier(
        client, headers, tax_id=f"NIT-{headers_name[:4]}"
    )
    detail = client.get(f"{PURCHASING_URL}/suppliers/{supplier_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["id"] == supplier_id


def test_invalid_token_is_rejected(client: TestClient) -> None:
    """Un token malformado responde 401, no 500."""
    response = client.get(
        f"{PURCHASING_URL}/suppliers",
        headers={"Authorization": "Bearer no-es-un-token"},
    )
    assert response.status_code == 401


# --------------------------------------------------------------------------- #
# Ciclo completo de compras por HTTP
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("headers_name", ["purchasing_headers", "admin_headers"])
def test_full_purchasing_cycle_over_http(
    request: pytest.FixtureRequest,
    client: TestClient,
    admin_headers: dict[str, str],
    headers_name: str,
) -> None:
    """Proveedor → OC → recepción → factura → abonos con los dos roles."""
    headers: dict[str, str] = request.getfixturevalue(headers_name)
    catalog = _create_catalog(client, admin_headers)
    supplier_id = _create_supplier(client, headers)
    received = _create_received_order(
        client,
        headers,
        supplier_id=supplier_id,
        product_id=catalog["product_id"],
        warehouse_id=catalog["warehouse_id"],
    )

    bill = _create_bill(client, headers, supplier_id=supplier_id, received=received)
    assert bill["code"].startswith(f"BILL-{_TODAY.year}-")
    assert bill["status"] == SupplierBillStatus.PENDING.value
    assert bill["total"] == "1190.00"
    assert bill["balance_due"] == "1190.00"

    pay = client.post(
        f"{PURCHASING_URL}/bills/{bill['id']}/pay",
        headers=headers,
        json={"amount": "190.00", "reference": "TRANS-1"},
    )
    assert pay.status_code == 200, pay.text
    assert pay.json()["status"] == SupplierBillStatus.PARTIALLY_PAID.value
    assert pay.json()["balance_due"] == "1000.00"

    pay = client.post(
        f"{PURCHASING_URL}/bills/{bill['id']}/pay",
        headers=headers,
        json={"amount": "1000.00"},
    )
    assert pay.status_code == 200, pay.text
    assert pay.json()["status"] == SupplierBillStatus.PAID.value
    assert pay.json()["balance_due"] == "0.00"

    history = client.get(
        f"{PURCHASING_URL}/bills/{bill['id']}/payments", headers=headers
    )
    assert history.status_code == 200
    assert [payment["amount"] for payment in history.json()] == ["190.00", "1000.00"]
    assert history.json()[0]["reference"] == "TRANS-1"


def test_bill_validation_and_immutability_over_http(
    client: TestClient,
    purchasing_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> None:
    """Los errores de dominio se traducen a 400/404/409 y PATCH/DELETE fallan."""
    catalog = _create_catalog(client, admin_headers)
    supplier_id = _create_supplier(client, purchasing_headers)
    received = _create_received_order(
        client,
        purchasing_headers,
        supplier_id=supplier_id,
        product_id=catalog["product_id"],
        warehouse_id=catalog["warehouse_id"],
    )
    bill = _create_bill(client, purchasing_headers, supplier_id=supplier_id, received=received)

    duplicate = client.post(
        f"{PURCHASING_URL}/bills",
        headers=purchasing_headers,
        json={
            "supplier_id": supplier_id,
            "goods_receipt_id": received["receipt"]["id"],
            "supplier_invoice_number": "F-2026-0001",
            "subtotal": "10.00",
            "tax_amount": "1.90",
        },
    )
    assert duplicate.status_code == 409

    overbill = client.post(
        f"{PURCHASING_URL}/bills",
        headers=purchasing_headers,
        json={
            "supplier_id": supplier_id,
            "goods_receipt_id": received["receipt"]["id"],
            "supplier_invoice_number": "F-2026-0002",
            "subtotal": "2000.00",
            "tax_amount": "380.00",
        },
    )
    assert overbill.status_code == 400

    missing = client.get(f"{PURCHASING_URL}/bills/99999", headers=purchasing_headers)
    assert missing.status_code == 404

    for method in ("PATCH", "DELETE"):
        response = client.request(
            method, f"{PURCHASING_URL}/bills/{bill['id']}", headers=purchasing_headers
        )
        assert response.status_code == 400

    void = client.post(
        f"{PURCHASING_URL}/bills/{bill['id']}/void", headers=purchasing_headers
    )
    assert void.status_code == 200
    assert void.json()["status"] == SupplierBillStatus.VOID.value


def test_order_transitions_over_http(
    client: TestClient,
    purchasing_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> None:
    """Aprobación, cancelación y cierre forzoso responden los códigos previstos."""
    catalog = _create_catalog(client, admin_headers)
    supplier_id = _create_supplier(client, purchasing_headers)
    order = client.post(
        f"{PURCHASING_URL}/orders",
        headers=purchasing_headers,
        json={
            "supplier_id": supplier_id,
            "expected_delivery_date": str(_TODAY + timedelta(days=5)),
            "items": [
                {
                    "product_id": catalog["product_id"],
                    "quantity": 2,
                    "unit_price": "100.00",
                    "tax_rate": "19.00",
                }
            ],
        },
    )
    assert order.status_code == 201
    order_id = order.json()["id"]

    approve = client.post(
        f"{PURCHASING_URL}/orders/{order_id}/approve", headers=purchasing_headers
    )
    assert approve.status_code == 200
    assert approve.json()["status"] == "APPROVED"

    conflict = client.post(
        f"{PURCHASING_URL}/orders/{order_id}/approve", headers=purchasing_headers
    )
    assert conflict.status_code == 409

    cancel = client.post(
        f"{PURCHASING_URL}/orders/{order_id}/cancel",
        headers=purchasing_headers,
        json={"reason": "Cambio de proveedor"},
    )
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "CANCELLED"

    forced = client.post(
        f"{PURCHASING_URL}/orders/{order_id}/force-close",
        headers=purchasing_headers,
    )
    assert forced.status_code == 409
