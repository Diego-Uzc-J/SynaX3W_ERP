"""Pruebas de aceptación del módulo de Ventas y Facturación (``sales``).

Cobertura de los escenarios críticos de ``specs/sales_spec.md`` (sección 5) y
de las reglas de negocio de la sección 3:

1. Clientes: alta, rechazo de ``tax_id`` duplicado y bloqueo de pedidos para
   clientes inactivos.
2. Conversión de pedido: confirmación ``CONFIRMED`` con descuento exacto del
   stock mediante un movimiento ``OUTBOUND`` e idempotencia del despacho.
3. Atomicidad: rechazo 400 por stock insuficiente (sin salidas parciales) y
   por límite de crédito excedido.
4. Facturación: emisión ``ISSUED``, inmutabilidad frente a PATCH/DELETE,
   pagos parciales/totales, anulación ``VOID`` y nota de crédito.
5. RBAC: 401 sin token y 403 para usuarios sin rol ``SALES``/``ADMINISTRATOR``.

Las pruebas usan SQLite en memoria y la API HTTP real (``TestClient``), por lo
que cubren router, dependencia RBAC, servicios, ORM y transacciones. El motor
desactiva el ``BEGIN`` implícito de ``pysqlite`` para que los ``ROLLBACK`` de
las pruebas de atomicidad reflejen el comportamiento de PostgreSQL.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Generator
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# ``backend`` debe estar en ``sys.path`` para importar el paquete ``src``.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# El engine global de ``src.core.database`` se crea al importar; se apunta a
# SQLite para que las pruebas no dependan de PostgreSQL ni del driver psycopg.
os.environ["DATABASE_URL"] = "sqlite://"

from src.core.database import Base, get_db  # noqa: E402
from src.core.security import create_access_token, hash_password  # noqa: E402
from src.main import app  # noqa: E402
from src.modules.inventory.models import MovementType  # noqa: E402
from src.modules.sales.models import InvoiceStatus  # noqa: E402
from src.modules.users.models import Role, RoleEnum, User  # noqa: E402

SALES_URL = "/api/v1/sales"
INVENTORY_URL = "/api/v1/inventory"

#: Hash calculado una sola vez para todos los usuarios de prueba.
_HASHED_PASSWORD = hash_password("Sales1234!")

#: Fecha de emisión y vencimiento usadas por las facturas de prueba.
_TODAY = date.today()
_DUE_DATE = _TODAY + timedelta(days=30)


# --------------------------------------------------------------------------- #
# Fixtures de base de datos y API
# --------------------------------------------------------------------------- #


@pytest.fixture()
def db_engine() -> Generator[Engine, None, None]:
    """Engine SQLite en memoria aislado por prueba.

    Se replica la receta de ``test_inventory.py``: el driver no emite ``BEGIN``
    antes de un ``SAVEPOINT``, por lo que un ``ROLLBACK`` no deshacía las filas
    creadas dentro del savepoint de ``_get_or_create_stock``.
    """
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
    """Sesión compartida entre la API y las aserciones de la prueba."""
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


@pytest.fixture(autouse=True)
def _disable_negative_stock_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Garantiza el comportamiento por defecto de ``ALLOW_NEGATIVE_STOCK``."""
    monkeypatch.delenv("ALLOW_NEGATIVE_STOCK", raising=False)


# --------------------------------------------------------------------------- #
# Fixtures de usuarios y RBAC
# --------------------------------------------------------------------------- #


def _role(db_session: Session, name: RoleEnum, modules: list[str]) -> Role:
    """Obtiene o crea un rol idempotentemente."""
    role = db_session.scalar(select(Role).where(Role.name == name))
    if role is None:
        role = Role(
            name=name,
            description=name.value,
            allowed_modules=modules,
        )
        db_session.add(role)
        db_session.flush()
    return role


def _user(
    db_session: Session,
    *,
    role: Role,
    username: str,
    email: str,
) -> User:
    """Crea un usuario activo con el rol indicado."""
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
    """Usuarios con rol ``ADMINISTRATOR``, ``SALES`` e ``INVENTORY``."""
    admin_role = _role(db_session, RoleEnum.ADMINISTRATOR, ["*"])
    sales_role = _role(
        db_session, RoleEnum.SALES, ["sales", "inventory:read"]
    )
    inventory_role = _role(
        db_session, RoleEnum.INVENTORY, ["inventory", "catalog:read"]
    )
    db_session.commit()

    return {
        "admin": _user(
            db_session,
            role=admin_role,
            username="sales_admin",
            email="sales-admin@example.com",
        ),
        "sales": _user(
            db_session,
            role=sales_role,
            username="vendedor",
            email="vendedor@example.com",
        ),
        "inventory": _user(
            db_session,
            role=inventory_role,
            username="bodega",
            email="bodega@example.com",
        ),
    }


def _headers(user: User) -> dict[str, str]:
    """Cabeceras ``Authorization`` para el usuario indicado."""
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.fixture()
def admin_headers(accounts: dict[str, User]) -> dict[str, str]:
    return _headers(accounts["admin"])


@pytest.fixture()
def sales_headers(accounts: dict[str, User]) -> dict[str, str]:
    return _headers(accounts["sales"])


@pytest.fixture()
def inventory_headers(accounts: dict[str, User]) -> dict[str, str]:
    return _headers(accounts["inventory"])


# --------------------------------------------------------------------------- #
# Fixtures de catálogo (productos, bodega y stock)
# --------------------------------------------------------------------------- #


def _create_product(
    client: TestClient,
    headers: dict[str, str],
    *,
    sku: str,
    unit_price: str = "100.00",
) -> dict[str, Any]:
    response = client.post(
        f"{INVENTORY_URL}/products",
        headers=headers,
        json={
            "sku": sku,
            "name": f"Producto {sku}",
            "unit_price": unit_price,
            "minimum_stock": 1,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _inbound(
    client: TestClient,
    headers: dict[str, str],
    *,
    product_id: int,
    warehouse_id: int,
    quantity: int,
) -> None:
    response = client.post(
        f"{INVENTORY_URL}/movements",
        headers=headers,
        json={
            "product_id": product_id,
            "movement_type": "INBOUND",
            "warehouse_destination_id": warehouse_id,
            "quantity": quantity,
            "reference_document": "OC-TEST-001",
            "created_by": "pytest",
        },
    )
    assert response.status_code == 201, response.text


@pytest.fixture()
def catalog(
    client: TestClient, admin_headers: dict[str, str]
) -> dict[str, Any]:
    """Dos productos con stock inicial y una bodega única para despacho."""
    response = client.post(
        f"{INVENTORY_URL}/warehouses",
        headers=admin_headers,
        json={"code": "BOD-SALES-01", "name": "Bodega de Ventas"},
    )
    assert response.status_code == 201, response.text
    warehouse = response.json()

    product_a = _create_product(
        client, admin_headers, sku="SKU-SALES-A", unit_price="100.00"
    )
    product_b = _create_product(
        client, admin_headers, sku="SKU-SALES-B", unit_price="50.00"
    )

    _inbound(
        client,
        admin_headers,
        product_id=product_a["id"],
        warehouse_id=warehouse["id"],
        quantity=20,
    )
    _inbound(
        client,
        admin_headers,
        product_id=product_b["id"],
        warehouse_id=warehouse["id"],
        quantity=2,
    )

    return {
        "warehouse_id": warehouse["id"],
        "product_a": product_a,
        "product_b": product_b,
    }


# --------------------------------------------------------------------------- #
# Utilidades de negocio
# --------------------------------------------------------------------------- #


def _create_customer(
    client: TestClient,
    headers: dict[str, str],
    *,
    tax_id: str = "900123456-1",
    credit_limit: str = "100000.00",
    is_active: bool = True,
) -> dict[str, Any]:
    response = client.post(
        f"{SALES_URL}/customers",
        headers=headers,
        json={
            "tax_id": tax_id,
            "company_name": "Aceros del Norte S.A.S.",
            "contact_name": "María Gómez",
            "email": f"cliente-{tax_id}@example.com",
            "address": "Calle 1 # 2-3",
            "credit_limit": credit_limit,
            "is_active": is_active,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_order(
    client: TestClient,
    headers: dict[str, str],
    *,
    customer_id: int,
    items: list[dict[str, Any]],
    code: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"customer_id": customer_id, "items": items}
    if code is not None:
        payload["code"] = code
    response = client.post(
        f"{SALES_URL}/orders", headers=headers, json=payload
    )
    assert response.status_code == 201, response.text
    return response.json()


def _line(
    product_id: int,
    *,
    quantity: int,
    unit_price: str = "100.00",
    tax_rate: str = "19.00",
) -> dict[str, Any]:
    return {
        "product_id": product_id,
        "quantity": quantity,
        "unit_price": unit_price,
        "tax_rate": tax_rate,
    }


def _confirm(
    client: TestClient,
    headers: dict[str, str],
    order_id: int,
    *,
    warehouse_id: int,
) -> dict[str, Any]:
    response = client.post(
        f"{SALES_URL}/orders/{order_id}/confirm",
        headers=headers,
        json={"warehouse_id": warehouse_id},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _stock_level(
    client: TestClient,
    headers: dict[str, str],
    *,
    product_id: int,
    warehouse_id: int,
) -> int:
    response = client.get(
        f"{INVENTORY_URL}/stock",
        headers=headers,
        params={"product_id": product_id, "warehouse_id": warehouse_id},
    )
    assert response.status_code == 200, response.text
    levels = response.json()
    return 0 if not levels else int(levels[0]["quantity"])


def _movements(
    client: TestClient,
    headers: dict[str, str],
    *,
    product_id: int | None = None,
) -> list[dict[str, Any]]:
    params = {"product_id": product_id} if product_id is not None else {}
    response = client.get(
        f"{INVENTORY_URL}/movements", headers=headers, params=params
    )
    assert response.status_code == 200, response.text
    return response.json()


def _issue_invoice(
    client: TestClient,
    headers: dict[str, str],
    **payload: Any,
) -> dict[str, Any]:
    response = client.post(
        f"{SALES_URL}/invoices", headers=headers, json=payload
    )
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------------- #
# Escenario 1: clientes y cliente inactivo
# --------------------------------------------------------------------------- #


def test_customer_creation_and_duplicate_tax_id(
    client: TestClient, sales_headers: dict[str, str]
) -> None:
    """Un cliente nuevo responde 201; el mismo ``tax_id`` responde 409."""
    customer = _create_customer(
        client, sales_headers, tax_id="900-DUP-1", credit_limit="5000.00"
    )
    assert customer["tax_id"] == "900-DUP-1"
    assert Decimal(customer["credit_limit"]) == Decimal("5000.00")
    assert customer["is_active"] is True

    duplicate = client.post(
        f"{SALES_URL}/customers",
        headers=sales_headers,
        json={
            "tax_id": "900-DUP-1",
            "company_name": "Otra empresa",
            "contact_name": "Otro contacto",
            "email": "otra@example.com",
            "address": "Calle 9",
        },
    )
    assert duplicate.status_code == 409, duplicate.text
    assert "900-DUP-1" in duplicate.json()["detail"]


def test_order_rejected_for_inactive_customer(
    client: TestClient,
    sales_headers: dict[str, str],
    catalog: dict[str, Any],
) -> None:
    """Crear o mantener pedidos para un cliente inactivo devuelve 409."""
    inactive = _create_customer(
        client,
        sales_headers,
        tax_id="900-INACTIVE-1",
        is_active=False,
    )
    response = client.post(
        f"{SALES_URL}/orders",
        headers=sales_headers,
        json={
            "customer_id": inactive["id"],
            "items": [_line(catalog["product_a"]["id"], quantity=1)],
        },
    )
    assert response.status_code == 409, response.text
    assert "inactivo" in response.json()["detail"]

    active = _create_customer(
        client, sales_headers, tax_id="900-INACTIVE-2"
    )
    deactivated = client.patch(
        f"{SALES_URL}/customers/{active['id']}",
        headers=sales_headers,
        json={"is_active": False},
    )
    assert deactivated.status_code == 200, deactivated.text

    response = client.post(
        f"{SALES_URL}/orders",
        headers=sales_headers,
        json={
            "customer_id": active["id"],
            "items": [_line(catalog["product_a"]["id"], quantity=1)],
        },
    )
    assert response.status_code == 409, response.text


# --------------------------------------------------------------------------- #
# Escenario 2: confirmación y descuento exacto de stock
# --------------------------------------------------------------------------- #


def test_confirm_order_discounts_exact_stock(
    client: TestClient,
    sales_headers: dict[str, str],
    admin_headers: dict[str, str],
    catalog: dict[str, Any],
) -> None:
    """Confirmar 3 unidades deja el stock en 17 y un único ``OUTBOUND``."""
    product_id = catalog["product_a"]["id"]
    warehouse_id = catalog["warehouse_id"]
    customer = _create_customer(client, sales_headers, tax_id="900-CONF-1")

    order = _create_order(
        client,
        sales_headers,
        customer_id=customer["id"],
        items=[_line(product_id, quantity=3)],
    )
    assert order["status"] == "DRAFT"
    assert order["code"] == f"PED-{_TODAY.year}-0001"
    assert Decimal(order["total"]) == Decimal("357.00")
    assert _stock_level(
        client, admin_headers, product_id=product_id, warehouse_id=warehouse_id
    ) == 20

    confirmed = _confirm(
        client,
        sales_headers,
        order["id"],
        warehouse_id=warehouse_id,
    )
    assert confirmed["status"] == "CONFIRMED"
    assert _stock_level(
        client, admin_headers, product_id=product_id, warehouse_id=warehouse_id
    ) == 17

    movements = _movements(client, admin_headers, product_id=product_id)
    outbound = [
        movement
        for movement in movements
        if movement["movement_type"] == MovementType.OUTBOUND.value
    ]
    assert len(outbound) == 1
    assert outbound[0]["quantity"] == 3
    assert outbound[0]["reference_document"] == order["code"]
    assert outbound[0]["warehouse_source_id"] == warehouse_id
    assert outbound[0]["created_by"] == "vendedor"

    # La confirmación es idempotente: no vuelve a descontar stock.
    repeated = _confirm(
        client,
        sales_headers,
        order["id"],
        warehouse_id=warehouse_id,
    )
    assert repeated["status"] == "CONFIRMED"
    assert _stock_level(
        client, admin_headers, product_id=product_id, warehouse_id=warehouse_id
    ) == 17
    outbound_after_retry = [
        movement
        for movement in _movements(client, admin_headers, product_id=product_id)
        if movement["movement_type"] == MovementType.OUTBOUND.value
    ]
    assert len(outbound_after_retry) == 1


# --------------------------------------------------------------------------- #
# Escenario 3: rechazo atómico por stock y por crédito
# --------------------------------------------------------------------------- #


def test_confirm_insufficient_stock_rolls_back_every_line(
    client: TestClient,
    sales_headers: dict[str, str],
    admin_headers: dict[str, str],
    catalog: dict[str, Any],
) -> None:
    """Si una línea no tiene stock, ninguna salida parcial queda registrada."""
    product_a = catalog["product_a"]["id"]
    product_b = catalog["product_b"]["id"]
    warehouse_id = catalog["warehouse_id"]
    customer = _create_customer(client, sales_headers, tax_id="900-STOCK-1")

    order = _create_order(
        client,
        sales_headers,
        customer_id=customer["id"],
        items=[
            _line(product_a, quantity=3),  # Hay 20: esta línea sería válida.
            _line(product_b, quantity=5),  # Solo hay 2: dispara el rollback.
        ],
    )

    response = client.post(
        f"{SALES_URL}/orders/{order['id']}/confirm",
        headers=sales_headers,
        json={"warehouse_id": warehouse_id},
    )
    assert response.status_code == 400, response.text
    assert "Stock insuficiente" in response.json()["detail"]

    # El pedido sigue en DRAFT y ningún saldo ni movimiento cambió.
    current = client.get(
        f"{SALES_URL}/orders/{order['id']}", headers=sales_headers
    )
    assert current.status_code == 200
    assert current.json()["status"] == "DRAFT"

    assert _stock_level(
        client, admin_headers, product_id=product_a, warehouse_id=warehouse_id
    ) == 20
    assert _stock_level(
        client, admin_headers, product_id=product_b, warehouse_id=warehouse_id
    ) == 2
    assert not [
        movement
        for movement in _movements(client, admin_headers)
        if movement["movement_type"] == MovementType.OUTBOUND.value
    ]


def test_confirm_rejected_when_credit_limit_exceeded(
    client: TestClient,
    sales_headers: dict[str, str],
    admin_headers: dict[str, str],
    catalog: dict[str, Any],
) -> None:
    """Con 900 facturados y límite 1000, un pedido de 119 se rechaza."""
    product_id = catalog["product_a"]["id"]
    warehouse_id = catalog["warehouse_id"]
    customer = _create_customer(
        client, sales_headers, tax_id="900-CREDIT-1", credit_limit="1000.00"
    )

    # Deuda vigente de 900 mediante una factura directa (no toca stock).
    invoice = _issue_invoice(
        client,
        sales_headers,
        customer_id=customer["id"],
        total="900.00",
        due_date=str(_DUE_DATE),
    )
    assert invoice["status"] == "ISSUED"
    assert Decimal(invoice["balance_due"]) == Decimal("900.00")

    order = _create_order(
        client,
        sales_headers,
        customer_id=customer["id"],
        items=[_line(product_id, quantity=1)],
    )
    assert Decimal(order["total"]) == Decimal("119.00")

    response = client.post(
        f"{SALES_URL}/orders/{order['id']}/confirm",
        headers=sales_headers,
        json={"warehouse_id": warehouse_id},
    )
    assert response.status_code == 400, response.text
    assert "crédito" in response.json()["detail"].lower()

    current = client.get(
        f"{SALES_URL}/orders/{order['id']}", headers=sales_headers
    )
    assert current.json()["status"] == "DRAFT"
    assert _stock_level(
        client, admin_headers, product_id=product_id, warehouse_id=warehouse_id
    ) == 20
    assert not [
        movement
        for movement in _movements(client, admin_headers)
        if movement["movement_type"] == MovementType.OUTBOUND.value
    ]


# --------------------------------------------------------------------------- #
# Escenario 4: facturación, inmutabilidad, pagos y nota crédito
# --------------------------------------------------------------------------- #


def test_invoice_cycle_immutability_payments_and_credit_note(
    client: TestClient,
    sales_headers: dict[str, str],
    catalog: dict[str, Any],
) -> None:
    """Emisión, bloqueo de edición, pagos, ``PAID`` y nota crédito."""
    customer = _create_customer(client, sales_headers, tax_id="900-INV-1")
    order = _create_order(
        client,
        sales_headers,
        customer_id=customer["id"],
        items=[_line(catalog["product_a"]["id"], quantity=10)],
    )
    _confirm(
        client,
        sales_headers,
        order["id"],
        warehouse_id=catalog["warehouse_id"],
    )

    invoice = _issue_invoice(
        client,
        sales_headers,
        sales_order_id=order["id"],
        customer_id=customer["id"],
        due_date=str(_DUE_DATE),
    )
    assert invoice["code"] == f"FAC-{_TODAY.year}-0001"
    assert invoice["sales_order_id"] == order["id"]
    assert invoice["status"] == InvoiceStatus.ISSUED.value
    assert Decimal(invoice["total"]) == Decimal("1190.00")
    assert Decimal(invoice["balance_due"]) == Decimal("1190.00")
    invoice_id = invoice["id"]

    # No se puede facturar dos veces el mismo pedido.
    duplicate = client.post(
        f"{SALES_URL}/invoices",
        headers=sales_headers,
        json={
            "sales_order_id": order["id"],
            "customer_id": customer["id"],
            "due_date": str(_DUE_DATE),
        },
    )
    assert duplicate.status_code == 409, duplicate.text

    # Inmutabilidad: ni edición ni borrado de una factura emitida.
    for method in ("patch", "delete"):
        response = getattr(client, method)(
            f"{SALES_URL}/invoices/{invoice_id}", headers=sales_headers
        )
        assert response.status_code == 400, response.text
        detail = response.json()["detail"]
        assert "VOID" in detail or "nota crédito" in detail

    # Pago parcial: el saldo baja y la factura sigue ISSUED.
    partial = client.post(
        f"{SALES_URL}/invoices/{invoice_id}/pay",
        headers=sales_headers,
        json={"amount": "400.00"},
    )
    assert partial.status_code == 200, partial.text
    assert Decimal(partial.json()["balance_due"]) == Decimal("790.00")
    assert partial.json()["status"] == InvoiceStatus.ISSUED.value

    # Sobrepago rechazado sin tocar el saldo.
    overpay = client.post(
        f"{SALES_URL}/invoices/{invoice_id}/pay",
        headers=sales_headers,
        json={"amount": "800.00"},
    )
    assert overpay.status_code == 400, overpay.text

    # Pago total: la factura pasa a PAID.
    total = client.post(
        f"{SALES_URL}/invoices/{invoice_id}/pay",
        headers=sales_headers,
        json={"amount": "790.00"},
    )
    assert total.status_code == 200, total.text
    assert Decimal(total.json()["balance_due"]) == Decimal("0.00")
    assert total.json()["status"] == InvoiceStatus.PAID.value

    payment_on_paid = client.post(
        f"{SALES_URL}/invoices/{invoice_id}/pay",
        headers=sales_headers,
        json={"amount": "1.00"},
    )
    assert payment_on_paid.status_code == 409, payment_on_paid.text

    # El historial conserva cada abono, incluido el pago total.
    payments = client.get(
        f"{SALES_URL}/invoices/{invoice_id}/payments",
        headers=sales_headers,
    )
    assert payments.status_code == 200, payments.text
    assert [
        (item["invoice_id"], Decimal(item["amount"]))
        for item in payments.json()
    ] == [
        (invoice_id, Decimal("400.00")),
        (invoice_id, Decimal("790.00")),
    ]
    assert payments.json()[0]["paid_at"] == str(_TODAY)

    # Nota crédito: contrapartida sin modificar la factura original.
    note = client.post(
        f"{SALES_URL}/invoices/{invoice_id}/credit-notes",
        headers=sales_headers,
        json={"amount": "190.00", "reason": "Devolución parcial"},
    )
    assert note.status_code == 201, note.text
    assert note.json()["code"] == f"NC-{_TODAY.year}-0001"
    assert Decimal(note.json()["amount"]) == Decimal("190.00")

    stored = client.get(
        f"{SALES_URL}/invoices/{invoice_id}", headers=sales_headers
    )
    assert stored.status_code == 200
    assert stored.json()["status"] == InvoiceStatus.PAID.value
    assert Decimal(stored.json()["balance_due"]) == Decimal("0.00")

    notes = client.get(
        f"{SALES_URL}/invoices/{invoice_id}/credit-notes",
        headers=sales_headers,
    )
    assert notes.status_code == 200
    assert [item["id"] for item in notes.json()] == [note.json()["id"]]

    # El acumulado de notas no puede superar el total facturado.
    excessive = client.post(
        f"{SALES_URL}/invoices/{invoice_id}/credit-notes",
        headers=sales_headers,
        json={"amount": "5000.00"},
    )
    assert excessive.status_code == 400, excessive.text


def test_void_invoice_and_invoice_requires_confirmed_order(
    client: TestClient,
    sales_headers: dict[str, str],
    catalog: dict[str, Any],
) -> None:
    """Un pedido DRAFT no se factura y una factura ISSUED puede anularse."""
    customer = _create_customer(client, sales_headers, tax_id="900-VOID-1")

    draft = _create_order(
        client,
        sales_headers,
        customer_id=customer["id"],
        items=[_line(catalog["product_a"]["id"], quantity=1)],
    )
    response = client.post(
        f"{SALES_URL}/invoices",
        headers=sales_headers,
        json={
            "sales_order_id": draft["id"],
            "customer_id": customer["id"],
            "due_date": str(_DUE_DATE),
        },
    )
    assert response.status_code == 409, response.text

    direct = _issue_invoice(
        client,
        sales_headers,
        customer_id=customer["id"],
        total="100.00",
        due_date=str(_DUE_DATE),
    )
    assert direct["sales_order_id"] is None

    voided = client.post(
        f"{SALES_URL}/invoices/{direct['id']}/void", headers=sales_headers
    )
    assert voided.status_code == 200, voided.text
    assert voided.json()["status"] == InvoiceStatus.VOID.value
    assert Decimal(voided.json()["balance_due"]) == Decimal("0.00")

    # Anular es idempotente; una factura VOID no admite pagos ni notas.
    repeated = client.post(
        f"{SALES_URL}/invoices/{direct['id']}/void", headers=sales_headers
    )
    assert repeated.status_code == 200
    assert repeated.json()["status"] == InvoiceStatus.VOID.value

    payment = client.post(
        f"{SALES_URL}/invoices/{direct['id']}/pay",
        headers=sales_headers,
        json={"amount": "10.00"},
    )
    assert payment.status_code == 409, payment.text

    note = client.post(
        f"{SALES_URL}/invoices/{direct['id']}/credit-notes",
        headers=sales_headers,
        json={"amount": "10.00"},
    )
    assert note.status_code == 409, note.text


# --------------------------------------------------------------------------- #
# Escenario 5: RBAC
# --------------------------------------------------------------------------- #


def test_sales_endpoints_require_sales_or_administrator_role(
    client: TestClient,
    sales_headers: dict[str, str],
    admin_headers: dict[str, str],
    inventory_headers: dict[str, str],
) -> None:
    """Sin token 401; ``INVENTORY`` 403; ``SALES`` y ``ADMINISTRATOR`` 200."""
    anonymous = client.get(f"{SALES_URL}/customers")
    assert anonymous.status_code == 401, anonymous.text

    forbidden = client.get(
        f"{SALES_URL}/customers", headers=inventory_headers
    )
    assert forbidden.status_code == 403, forbidden.text

    for method, path in (
        ("get", f"{SALES_URL}/customers"),
        ("get", f"{SALES_URL}/orders"),
        ("get", f"{SALES_URL}/invoices"),
    ):
        allowed_sales = getattr(client, method)(path, headers=sales_headers)
        allowed_admin = getattr(client, method)(path, headers=admin_headers)
        assert allowed_sales.status_code == 200, allowed_sales.text
        assert allowed_admin.status_code == 200, allowed_admin.text

    create_forbidden = client.post(
        f"{SALES_URL}/customers",
        headers=inventory_headers,
        json={
            "tax_id": "900-RBAC-1",
            "company_name": "No autorizado",
            "contact_name": "Contacto",
            "email": "rbac@example.com",
            "address": "Calle 1",
        },
    )
    assert create_forbidden.status_code == 403, create_forbidden.text
