"""Pruebas de aceptación del módulo de inventario (spec, sección 5).

Cobertura por escenario:

1. Creación de entrada: un ``INBOUND`` de 10 unidades sobre stock 0 deja el
   saldo exactamente en 10 y crea el registro en el historial.
2. Bloqueo de stock negativo: un ``OUTBOUND`` de 5 unidades con 2 disponibles
   se rechaza con HTTP 400 y un mensaje de stock insuficiente, sin alterar ni
   el saldo ni el historial.
3. SKU duplicado: un segundo producto con el mismo SKU se rechaza y el mensaje
   identifica el SKU en uso (alta y actualización).
4. Detección de stock bajo: la API expone ``minimum_stock`` y la existencia
   actual, datos con los que ``ProductList.tsx`` decide la insignia de alerta.
5. Código de almacén duplicado: un segundo almacén con el mismo código se
   rechaza con un mensaje que identifica el código en uso.

Los escenarios 4 y 5 combinan backend y frontend. Aquí se prueba el contrato
de datos y el rechazo del backend; la insignia visual y el mensaje inline del
formulario se validan en el E2E de Chrome headless descrito en ``MEMORY.md``.

Desviación consciente de la spec: el escenario 3 admite 400 o 422, pero la
implementación responde 409 Conflict (ver ``router._ERROR_STATUS``), que es el
código semánticamente correcto para un recurso duplicado y el que el frontend
ya muestra inline. Estas pruebas fijan ese contrato real.

Además de los cinco escenarios se cubren las reglas de negocio de la sección 3
que los sustentan: unicidad de SKU y código, control de stock negativo
(incluido ``ALLOW_NEGATIVE_STOCK``), inmutabilidad del historial y validación
de bodegas en transferencias. También se comprueba la atomicidad: un rechazo
no deja saldos ni movimientos parciales.

Las pruebas usan SQLite en memoria y la API HTTP real (``TestClient``), por lo
que validan el contrato completo: router, servicios, reglas de negocio y ORM.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import create_engine, event, func, select
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
from src.modules.inventory.models import (  # noqa: E402
    Stock,
    StockMovement,
)
from src.modules.inventory.services import ImmutableMovementError  # noqa: E402

MOVEMENTS_URL = "/api/v1/inventory/movements"
PRODUCTS_URL = "/api/v1/inventory/products"
WAREHOUSES_URL = "/api/v1/inventory/warehouses"
STOCK_URL = "/api/v1/inventory/stock"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture()
def db_engine() -> Generator[Engine, None, None]:
    """Engine SQLite en memoria, aislado por prueba.

    ``pysqlite`` no emite ``BEGIN`` antes de un ``SAVEPOINT`` con su modo de
    transacción heredado, lo que hace que ``rollback()`` no deshaga las filas
    creadas dentro de un savepoint (``_get_or_create_stock``). Se aplica la
    receta documentada por SQLAlchemy: desactivar el manejo implícito del
    driver y emitir ``BEGIN`` explícitamente, para que las pruebas de
    atomicidad reflejen el comportamiento real de PostgreSQL.
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


@pytest.fixture()
def second_warehouse(client: TestClient) -> dict:
    """Segunda bodega, usada en transferencias y pruebas de atomicidad."""
    response = client.post(
        WAREHOUSES_URL,
        json={
            "code": "BOD-MED-02",
            "name": "Bodega Secundaria Medellín",
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


def _stock_row_count(db_session: Session) -> int:
    """Cantidad de filas en ``stocks`` (útil para comprobar atomicidad)."""
    return db_session.scalar(select(func.count()).select_from(Stock))


def _movement_count(db_session: Session) -> int:
    return db_session.scalar(select(func.count()).select_from(StockMovement))


def _history(client: TestClient, **params: int | str) -> list[dict]:
    """Consulta el historial de movimientos con los filtros indicados."""
    response = client.get(MOVEMENTS_URL, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _stock_levels(client: TestClient, **params: int) -> list[dict]:
    """Consulta los saldos actuales con los filtros indicados."""
    response = client.get(STOCK_URL, params=params)
    assert response.status_code == 200, response.text
    return response.json()


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


def _validation_text(response: Response) -> str:
    """Serializa el ``detail`` de un 422 para buscar el mensaje del validador."""
    return str(response.json()["detail"])


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
    assert _stock_row_count(db_session) == 0
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
    assert _stock_row_count(db_session) == 1

    # ...el endpoint de existencias lo refleja...
    stock_levels = _stock_levels(client, product_id=product_id)
    assert len(stock_levels) == 1
    assert stock_levels[0]["product_id"] == product_id
    assert stock_levels[0]["warehouse_id"] == warehouse_id
    assert stock_levels[0]["quantity"] == 10

    # ...y se creó exactamente un registro en el historial.
    assert _movement_count(db_session) == 1
    history = _history(client, product_id=product_id)
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
    stock_levels = _stock_levels(client, product_id=product_id)
    assert [level["quantity"] for level in stock_levels] == [2]
    history = _history(client, product_id=product_id)
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


def test_failed_outbound_does_not_create_stock_or_history(
    client: TestClient,
    db_session: Session,
    product: dict,
    warehouse: dict,
    second_warehouse: dict,
) -> None:
    """Atomicidad: un 400 no deja fila de stock en la bodega sin saldo."""
    product_id = product["id"]

    inbound = _register_movement(
        client,
        product_id=product_id,
        movement_type="INBOUND",
        quantity=2,
        warehouse_destination_id=warehouse["id"],
    )
    assert inbound.status_code == 201, inbound.text
    assert _stock_row_count(db_session) == 1

    # La segunda bodega no tiene fila de stock (disponible 0).
    response = _register_movement(
        client,
        product_id=product_id,
        movement_type="OUTBOUND",
        quantity=5,
        warehouse_source_id=second_warehouse["id"],
    )

    assert response.status_code == 400, response.text
    assert "disponible 0" in response.json()["detail"].lower()

    # Ni fila de stock nueva, ni movimiento, ni cambios en el saldo original.
    assert _stock_row_count(db_session) == 1
    assert _movement_count(db_session) == 1
    assert _quantity(db_session, product_id, warehouse["id"]) == 2
    assert _stock_levels(client, warehouse_id=second_warehouse["id"]) == []


# --------------------------------------------------------------------------- #
# Escenario 3: SKU duplicado
# --------------------------------------------------------------------------- #


def test_duplicate_sku_on_create_returns_409_with_clear_message(
    client: TestClient,
    db_session: Session,
    product: dict,
) -> None:
    """Un segundo producto con el mismo SKU se rechaza sin persistirse."""
    response = client.post(
        PRODUCTS_URL,
        json={
            "sku": product["sku"],
            "name": "Laptop Industrial (duplicada)",
            "unit_price": "100.00",
        },
    )

    # La spec admite 400/422; la implementación responde 409 Conflict.
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert "SKU" in detail
    assert product["sku"] in detail

    # El catálogo conserva un único producto con ese SKU.
    products = client.get(PRODUCTS_URL).json()
    assert [item["sku"] for item in products] == [product["sku"]]
    assert _movement_count(db_session) == 0


def test_duplicate_sku_on_update_returns_409_and_keeps_target(
    client: TestClient,
    product: dict,
) -> None:
    """PATCH tampoco permite reutilizar el SKU de otro producto."""
    created = client.post(
        PRODUCTS_URL,
        json={
            "sku": "LAP-IND-002",
            "name": "Laptop Industrial 2",
            "unit_price": "999.00",
        },
    )
    assert created.status_code == 201, created.text
    other = created.json()

    response = client.patch(
        f"{PRODUCTS_URL}/{other['id']}",
        json={"sku": product["sku"]},
    )

    assert response.status_code == 409, response.text
    assert product["sku"] in response.json()["detail"]

    # El producto objetivo conserva su SKU original.
    refreshed = client.get(f"{PRODUCTS_URL}/{other['id']}").json()
    assert refreshed["sku"] == "LAP-IND-002"


# --------------------------------------------------------------------------- #
# Escenario 4: detección de stock bajo
# --------------------------------------------------------------------------- #


def test_low_stock_threshold_is_derivable_from_api_data(
    client: TestClient,
    db_session: Session,
    product: dict,
    warehouse: dict,
) -> None:
    """La API expone los datos con los que la UI decide la insignia de alerta.

    ``ProductList.tsx`` compara la existencia total del producto con su
    ``minimum_stock``. El escenario pide 3 unidades y un mínimo de 5; aquí se
    verifica el contrato de datos y la frontera (5 ya no es bajo mínimo). La
    representación visual se cubre en el E2E de Chrome headless.
    """
    product_id = product["id"]
    warehouse_id = warehouse["id"]

    inbound = _register_movement(
        client,
        product_id=product_id,
        movement_type="INBOUND",
        quantity=3,
        warehouse_destination_id=warehouse_id,
    )
    assert inbound.status_code == 201, inbound.text

    detail = client.get(f"{PRODUCTS_URL}/{product_id}").json()
    levels = _stock_levels(client, product_id=product_id)

    assert detail["minimum_stock"] == 5
    assert len(levels) == 1
    current_stock = levels[0]["quantity"]
    assert current_stock == 3
    assert current_stock < detail["minimum_stock"]

    # Frontera: con exactamente el mínimo la alerta desaparece.
    top_up = _register_movement(
        client,
        product_id=product_id,
        movement_type="INBOUND",
        quantity=2,
        warehouse_destination_id=warehouse_id,
    )
    assert top_up.status_code == 201, top_up.text
    assert _quantity(db_session, product_id, warehouse_id) == 5
    assert _quantity(db_session, product_id, warehouse_id) >= detail[
        "minimum_stock"
    ]


# --------------------------------------------------------------------------- #
# Escenario 5: código de almacén duplicado
# --------------------------------------------------------------------------- #


def test_duplicate_warehouse_code_returns_409_with_clear_message(
    client: TestClient,
    warehouse: dict,
) -> None:
    """Un segundo almacén con el mismo código se rechaza y lo identifica."""
    response = client.post(
        WAREHOUSES_URL,
        json={
            "code": warehouse["code"],
            "name": "Bodega duplicada",
            "address": "Otra dirección",
        },
    )

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert "código" in detail.lower()
    assert warehouse["code"] in detail

    # Solo existe el almacén original.
    warehouses = client.get(
        WAREHOUSES_URL, params={"active_only": False}
    ).json()
    assert [item["code"] for item in warehouses] == [warehouse["code"]]


# --------------------------------------------------------------------------- #
# Regla 2: transferencias y stock negativo
# --------------------------------------------------------------------------- #


def test_transfer_moves_stock_between_warehouses(
    client: TestClient,
    db_session: Session,
    product: dict,
    warehouse: dict,
    second_warehouse: dict,
) -> None:
    """Transfiere: descuenta origen, suma destino y crea un solo movimiento."""
    product_id = product["id"]
    source_id = warehouse["id"]
    destination_id = second_warehouse["id"]

    assert (
        _register_movement(
            client,
            product_id=product_id,
            movement_type="INBOUND",
            quantity=10,
            warehouse_destination_id=source_id,
        ).status_code
        == 201
    )

    response = _register_movement(
        client,
        product_id=product_id,
        movement_type="TRANSFER",
        quantity=4,
        warehouse_source_id=source_id,
        warehouse_destination_id=destination_id,
        reference_document="TR-2026-001",
    )

    assert response.status_code == 201, response.text
    movement = response.json()
    assert movement["movement_type"] == "TRANSFER"
    assert movement["warehouse_source_id"] == source_id
    assert movement["warehouse_destination_id"] == destination_id

    assert _quantity(db_session, product_id, source_id) == 6
    assert _quantity(db_session, product_id, destination_id) == 4
    assert _movement_count(db_session) == 2

    destination_levels = _stock_levels(client, warehouse_id=destination_id)
    assert [level["quantity"] for level in destination_levels] == [4]


def test_transfer_to_same_warehouse_is_rejected(
    client: TestClient,
    db_session: Session,
    product: dict,
    warehouse: dict,
) -> None:
    """Regla 4: origen y destino de una transferencia deben ser distintos."""
    response = _register_movement(
        client,
        product_id=product["id"],
        movement_type="TRANSFER",
        quantity=1,
        warehouse_source_id=warehouse["id"],
        warehouse_destination_id=warehouse["id"],
    )

    assert response.status_code == 422, response.text
    assert "distintas" in _validation_text(response)
    assert _stock_row_count(db_session) == 0
    assert _movement_count(db_session) == 0


def test_transfer_requires_both_warehouses(
    client: TestClient,
    db_session: Session,
    product: dict,
    warehouse: dict,
) -> None:
    """Una transferencia sin origen o sin destino no pasa la validación."""
    missing_destination = _register_movement(
        client,
        product_id=product["id"],
        movement_type="TRANSFER",
        quantity=1,
        warehouse_source_id=warehouse["id"],
    )
    missing_source = _register_movement(
        client,
        product_id=product["id"],
        movement_type="TRANSFER",
        quantity=1,
        warehouse_destination_id=warehouse["id"],
    )

    assert missing_destination.status_code == 422, missing_destination.text
    assert missing_source.status_code == 422, missing_source.text
    assert "origen y de destino" in _validation_text(missing_destination)
    assert "origen y de destino" in _validation_text(missing_source)
    assert _movement_count(db_session) == 0


def test_simple_movements_reject_the_opposite_warehouse(
    client: TestClient,
    db_session: Session,
    product: dict,
    warehouse: dict,
    second_warehouse: dict,
) -> None:
    """INBOUND no admite origen y OUTBOUND no admite destino."""
    inbound_with_source = _register_movement(
        client,
        product_id=product["id"],
        movement_type="INBOUND",
        quantity=1,
        warehouse_source_id=warehouse["id"],
        warehouse_destination_id=second_warehouse["id"],
    )
    outbound_with_destination = _register_movement(
        client,
        product_id=product["id"],
        movement_type="OUTBOUND",
        quantity=1,
        warehouse_source_id=warehouse["id"],
        warehouse_destination_id=second_warehouse["id"],
    )

    assert inbound_with_source.status_code == 422, inbound_with_source.text
    assert outbound_with_destination.status_code == 422, (
        outbound_with_destination.text
    )
    assert "no admite bodega de origen" in _validation_text(
        inbound_with_source
    )
    assert "no admite bodega de destino" in _validation_text(
        outbound_with_destination
    )
    assert _movement_count(db_session) == 0


def test_failed_transfer_is_atomic(
    client: TestClient,
    db_session: Session,
    product: dict,
    warehouse: dict,
    second_warehouse: dict,
) -> None:
    """Si una transferencia excede el saldo, no deja rastro en ninguna bodega."""
    product_id = product["id"]
    source_id = warehouse["id"]
    destination_id = second_warehouse["id"]

    assert (
        _register_movement(
            client,
            product_id=product_id,
            movement_type="INBOUND",
            quantity=1,
            warehouse_destination_id=source_id,
        ).status_code
        == 201
    )

    response = _register_movement(
        client,
        product_id=product_id,
        movement_type="TRANSFER",
        quantity=3,
        warehouse_source_id=source_id,
        warehouse_destination_id=destination_id,
    )

    assert response.status_code == 400, response.text
    assert "stock insuficiente" in response.json()["detail"].lower()

    # El origen conserva su unidad y el destino no llegó a tener fila de stock.
    assert _quantity(db_session, product_id, source_id) == 1
    assert _stock_row_count(db_session) == 1
    assert _movement_count(db_session) == 1
    assert _stock_levels(client, warehouse_id=destination_id) == []


def test_allow_negative_stock_flag_permits_negative_outbound(
    client: TestClient,
    db_session: Session,
    product: dict,
    warehouse: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Con ``ALLOW_NEGATIVE_STOCK`` activo, la salida deja saldo negativo."""
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

    monkeypatch.setenv("ALLOW_NEGATIVE_STOCK", "true")

    response = _register_movement(
        client,
        product_id=product_id,
        movement_type="OUTBOUND",
        quantity=5,
        warehouse_source_id=warehouse_id,
    )

    assert response.status_code == 201, response.text
    assert _quantity(db_session, product_id, warehouse_id) == -3
    assert _movement_count(db_session) == 2


# --------------------------------------------------------------------------- #
# Regla 3: inmutabilidad del historial
# --------------------------------------------------------------------------- #


def test_adjustment_corrects_balance_with_a_new_movement(
    client: TestClient,
    db_session: Session,
    product: dict,
    warehouse: dict,
) -> None:
    """La corrección se hace con ADJUSTMENT; el INBOUND original no cambia."""
    product_id = product["id"]
    warehouse_id = warehouse["id"]

    assert (
        _register_movement(
            client,
            product_id=product_id,
            movement_type="INBOUND",
            quantity=10,
            warehouse_destination_id=warehouse_id,
        ).status_code
        == 201
    )

    decrease = _register_movement(
        client,
        product_id=product_id,
        movement_type="ADJUSTMENT",
        quantity=4,
        warehouse_source_id=warehouse_id,
        reference_document="AJ-2026-001",
    )
    increase = _register_movement(
        client,
        product_id=product_id,
        movement_type="ADJUSTMENT",
        quantity=2,
        warehouse_destination_id=warehouse_id,
        reference_document="AJ-2026-002",
    )

    assert decrease.status_code == 201, decrease.text
    assert increase.status_code == 201, increase.text
    assert _quantity(db_session, product_id, warehouse_id) == 8
    assert _movement_count(db_session) == 3

    history = _history(client, product_id=product_id)
    assert [item["movement_type"] for item in history] == [
        "ADJUSTMENT",
        "ADJUSTMENT",
        "INBOUND",
    ]
    assert history[-1]["quantity"] == 10


def test_stock_movement_cannot_be_updated_nor_deleted_in_orm(
    client: TestClient,
    db_session: Session,
    product: dict,
    warehouse: dict,
) -> None:
    """Los listeners de SQLAlchemy bloquean update y delete del historial."""
    response = _register_movement(
        client,
        product_id=product["id"],
        movement_type="INBOUND",
        quantity=5,
        warehouse_destination_id=warehouse["id"],
    )
    assert response.status_code == 201, response.text
    movement_id = response.json()["id"]

    movement = db_session.get(StockMovement, movement_id)
    assert movement is not None

    movement.quantity = 99
    with pytest.raises(ImmutableMovementError):
        db_session.commit()
    db_session.rollback()

    persisted = db_session.get(StockMovement, movement_id)
    assert persisted is not None
    assert persisted.quantity == 5

    db_session.delete(persisted)
    with pytest.raises(ImmutableMovementError):
        db_session.commit()
    db_session.rollback()

    assert db_session.get(StockMovement, movement_id) is not None
    assert _movement_count(db_session) == 1


def test_movement_history_exposes_no_update_or_delete_endpoint(
    client: TestClient,
    product: dict,
    warehouse: dict,
) -> None:
    """La API solo publica POST y GET para el historial (regla 3)."""
    created = _register_movement(
        client,
        product_id=product["id"],
        movement_type="INBOUND",
        quantity=1,
        warehouse_destination_id=warehouse["id"],
    )
    assert created.status_code == 201, created.text
    movement_id = created.json()["id"]

    patch = client.patch(f"{MOVEMENTS_URL}/{movement_id}", json={"quantity": 2})
    delete = client.delete(f"{MOVEMENTS_URL}/{movement_id}")

    assert patch.status_code in {404, 405}, patch.text
    assert delete.status_code in {404, 405}, delete.text


# --------------------------------------------------------------------------- #
# Validaciones de entrada y recursos inexistentes
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("quantity", [0, -1])
def test_non_positive_quantity_is_rejected(
    client: TestClient,
    db_session: Session,
    product: dict,
    warehouse: dict,
    quantity: int,
) -> None:
    """La cantidad de un movimiento debe ser siempre mayor que cero."""
    response = _register_movement(
        client,
        product_id=product["id"],
        movement_type="INBOUND",
        quantity=quantity,
        warehouse_destination_id=warehouse["id"],
    )

    assert response.status_code == 422, response.text
    errors = response.json()["detail"]
    assert any(error["loc"][-1] == "quantity" for error in errors)
    assert _movement_count(db_session) == 0
    assert _stock_row_count(db_session) == 0


def test_movement_with_unknown_product_returns_404(
    client: TestClient,
    db_session: Session,
    warehouse: dict,
) -> None:
    """Un producto inexistente no puede recibir movimientos."""
    response = _register_movement(
        client,
        product_id=999_999,
        movement_type="INBOUND",
        quantity=1,
        warehouse_destination_id=warehouse["id"],
    )

    assert response.status_code == 404, response.text
    assert "999999" in response.json()["detail"]
    assert _movement_count(db_session) == 0


def test_movement_with_unknown_warehouse_returns_404(
    client: TestClient,
    db_session: Session,
    product: dict,
) -> None:
    """Una bodega inexistente no puede recibir ni entregar movimientos."""
    response = _register_movement(
        client,
        product_id=product["id"],
        movement_type="INBOUND",
        quantity=1,
        warehouse_destination_id=999_999,
    )

    assert response.status_code == 404, response.text
    assert "999999" in response.json()["detail"]
    assert _movement_count(db_session) == 0
    assert _stock_row_count(db_session) == 0
