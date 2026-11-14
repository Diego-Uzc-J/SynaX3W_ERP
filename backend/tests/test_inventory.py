"""Pruebas de aceptación del módulo de inventario (spec, sección 5).

Escenario 1: una entrada ``INBOUND`` de 10 unidades actualiza el stock a 10 y
registra el movimiento en el historial.

Escenario 2: una salida ``OUTBOUND`` de 5 unidades sobre un stock de 2 se
rechaza con HTTP 400 y no altera ni el stock ni el historial.

Las pruebas usan SQLite en memoria y la API HTTP real (``TestClient``), por lo
que validan el contrato completo: router, servicios, reglas de negocio y ORM.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# ``backend`` debe estar en sys.path para importar el paquete ``src``.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# El engine global de ``src.core.database`` se crea al importar; se apunta a
# SQLite para que las pruebas no dependan de PostgreSQL ni del driver psycopg.
os.environ["DATABASE_URL"] = "sqlite://"

from src.core.database import Base, get_db  # noqa: E402
from src.main import app  # noqa: E402
from src.modules.inventory.models import Stock, StockMovement  # noqa: E402

MOVEMENTS_URL = "/api/v1/inventory/movements"
PRODUCTS_URL = "/api/v1/inventory/products"
WAREHOUSES_URL = "/api/v1/inventory/warehouses"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture()
def db_engine() -> Generator[Engine, None, None]:
    """Engine SQLite en memoria, aislado por prueba."""
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
    """Sesión compartida entre la API y las aserciones de la prueba."""
    session_factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    with session_factory() as session:
        yield session


@pytest.fixture()
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """Cliente HTTP con la dependencia ``get_db`` apuntando a la BD de prueba."""

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


@pytest.fixture()
def product(client: TestClient) -> dict:
    """Producto de ejemplo con stock inicial 0."""
    response = client.post(
        PRODUCTS_URL,
        json={
            "sku": "LAP-IND-001",
            "name": "Laptop Industrial",
            "description": "Laptop Industrial Rugged",
            "unit_price": "1899.90",
            "minimum_stock": 5,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture()
def warehouse(client: TestClient) -> dict:
    """Bodega de ejemplo."""
    response = client.post(
        WAREHOUSES_URL,
        json={
            "code": "BOD-MED-01",
            "name": "Bodega Principal Medellín",
            "address": "Calle 1 # 2-3",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #


def _quantity(db_session: Session, product_id: int, warehouse_id: int) -> int:
    """Saldo actual, o 0 si aún no existe fila en ``stocks``."""
    quantity = db_session.scalar(
        select(Stock.quantity).where(
            Stock.product_id == product_id,
            Stock.warehouse_id == warehouse_id,
        )
    )
    return 0 if quantity is None else quantity


def _movement_count(db_session: Session) -> int:
    return db_session.scalar(select(func.count()).select_from(StockMovement))


def _register_movement(
    client: TestClient,
    *,
    product_id: int,
    movement_type: str,
    quantity: int,
    warehouse_source_id: int | None = None,
    warehouse_destination_id: int | None = None,
    reference_document: str = "OC-2026-001",
) -> Response:
    return client.post(
        MOVEMENTS_URL,
        json={
            "product_id": product_id,
            "movement_type": movement_type,
            "quantity": quantity,
            "warehouse_source_id": warehouse_source_id,
            "warehouse_destination_id": warehouse_destination_id,
            "reference_document": reference_document,
            "created_by": "pytest",
        },
    )


# --------------------------------------------------------------------------- #
# Escenario 1: creación de entrada de inventario
# --------------------------------------------------------------------------- #


def test_inbound_updates_stock_to_ten_and_creates_history(
    client: TestClient,
    db_session: Session,
    product: dict,
    warehouse: dict,
) -> None:
    """INBOUND de 10 sobre stock 0 deja 10 unidades y un registro histórico."""
    product_id = product["id"]
    warehouse_id = warehouse["id"]

    # Dado un producto y una bodega con stock 0.
    assert _quantity(db_session, product_id, warehouse_id) == 0
    assert _movement_count(db_session) == 0

    # Cuando se registra un movimiento INBOUND de 10 unidades.
    response = _register_movement(
        client,
        product_id=product_id,
        movement_type="INBOUND",
        quantity=10,
        warehouse_destination_id=warehouse_id,
    )

    # Entonces responde 201 y el historial refleja el movimiento.
    assert response.status_code == 201, response.text
    movement = response.json()
    assert movement["id"] > 0
    assert movement["movement_type"] == "INBOUND"
    assert movement["product_id"] == product_id
    assert movement["quantity"] == 10
    assert movement["warehouse_source_id"] is None
    assert movement["warehouse_destination_id"] == warehouse_id
    assert movement["reference_document"] == "OC-2026-001"

    # ...el stock queda exactamente en 10...
    assert _quantity(db_session, product_id, warehouse_id) == 10

    # ...y se creó exactamente un registro en el historial.
    assert _movement_count(db_session) == 1
    history = client.get(
        MOVEMENTS_URL, params={"product_id": product_id}
    ).json()
    assert [item["id"] for item in history] == [movement["id"]]


# --------------------------------------------------------------------------- #
# Escenario 2: bloqueo de stock negativo
# --------------------------------------------------------------------------- #


def test_outbound_above_available_stock_returns_400(
    client: TestClient,
    db_session: Session,
    product: dict,
    warehouse: dict,
) -> None:
    """OUTBOUND de 5 con 2 disponibles devuelve 400 y no altera nada."""
    product_id = product["id"]
    warehouse_id = warehouse["id"]

    # Dado un producto con 2 unidades en la bodega.
    inbound = _register_movement(
        client,
        product_id=product_id,
        movement_type="INBOUND",
        quantity=2,
        warehouse_destination_id=warehouse_id,
    )
    assert inbound.status_code == 201, inbound.text
    assert _quantity(db_session, product_id, warehouse_id) == 2
    assert _movement_count(db_session) == 1

    # Cuando se intenta registrar un OUTBOUND de 5 unidades.
    response = _register_movement(
        client,
        product_id=product_id,
        movement_type="OUTBOUND",
        quantity=5,
        warehouse_source_id=warehouse_id,
        reference_document="FAC-8921",
    )

    # Entonces el sistema rechaza con 400 y un mensaje de stock insuficiente.
    assert response.status_code == 400, response.text
    detail = response.json()["detail"].lower()
    assert "stock insuficiente" in detail
    assert "disponible 2" in detail
    assert "solicitado 5" in detail

    # El stock permanece en 2 y el historial no registra el intento.
    assert _quantity(db_session, product_id, warehouse_id) == 2
    assert _movement_count(db_session) == 1
    history = client.get(
        MOVEMENTS_URL, params={"product_id": product_id}
    ).json()
    assert len(history) == 1
    assert history[0]["movement_type"] == "INBOUND"


def test_outbound_exactly_available_stock_is_allowed(
    client: TestClient,
    db_session: Session,
    product: dict,
    warehouse: dict,
) -> None:
    """Frontera del escenario 2: consumir todo el stock (2) sí es válido."""
    product_id = product["id"]
    warehouse_id = warehouse["id"]

    assert (
        _register_movement(
            client,
            product_id=product_id,
            movement_type="INBOUND",
            quantity=2,
            warehouse_destination_id=warehouse_id,
        ).status_code
        == 201
    )

    response = _register_movement(
        client,
        product_id=product_id,
        movement_type="OUTBOUND",
        quantity=2,
        warehouse_source_id=warehouse_id,
        reference_document="FAC-8922",
    )

    assert response.status_code == 201, response.text
    assert _quantity(db_session, product_id, warehouse_id) == 0
    assert _movement_count(db_session) == 2
