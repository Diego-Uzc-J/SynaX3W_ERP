"""Servicios de dominio del módulo de Inventario y Logística.

Implementa las reglas de negocio de ``specs/inventory_spec.md`` (sección 3):

1. Unicidad de SKU (y de código de almacén) antes de persistir.
2. Control de stock negativo en salidas y transferencias, salvo que
   ``ALLOW_NEGATIVE_STOCK`` esté activo.
3. Inmutabilidad del historial de ``StockMovement``: no se exponen operaciones
   de actualización ni borrado, y los listeners de SQLAlchemy bloquean ambos
   a nivel de instancia ORM.
4. Validación de bodegas: una transferencia exige origen y destino distintos.

Cada movimiento se registra en una única transacción: el saldo de ``Stock`` y
la fila de historial se confirman o revierten juntos.
"""

from __future__ import annotations

import os
from datetime import datetime

from sqlalchemy import event, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.modules.inventory.models import (
    MovementType,
    Product,
    Stock,
    StockMovement,
    Warehouse,
)
from src.modules.inventory.schemas import (
    ProductCreate,
    ProductUpdate,
    StockMovementCreate,
    WarehouseCreate,
    WarehouseUpdate,
)

__all__ = [
    "DuplicateResourceError",
    "ImmutableMovementError",
    "InsufficientStockError",
    "InventoryError",
    "InvalidMovementError",
    "ResourceNotFoundError",
    "create_product",
    "create_stock_movement",
    "create_warehouse",
    "get_product",
    "get_warehouse",
    "list_products",
    "list_stock_movements",
    "list_warehouses",
    "update_product",
    "update_warehouse",
]


# --------------------------------------------------------------------------- #
# Excepciones de dominio
# --------------------------------------------------------------------------- #


class InventoryError(Exception):
    """Error base del módulo de inventario."""


class ResourceNotFoundError(InventoryError):
    """El recurso solicitado no existe."""


class DuplicateResourceError(InventoryError):
    """Se intentó persistir un valor que debe ser único."""


class InvalidMovementError(InventoryError):
    """El movimiento no cumple las reglas de bodegas del dominio."""


class InsufficientStockError(InventoryError):
    """La operación dejaría el stock en negativo y el flag está desactivado."""

    def __init__(
        self,
        *,
        product_id: int,
        warehouse_id: int,
        available: int,
        requested: int,
    ) -> None:
        self.product_id = product_id
        self.warehouse_id = warehouse_id
        self.available = available
        self.requested = requested
        super().__init__(
            "Stock insuficiente para el producto "
            f"{product_id} en el almacén {warehouse_id}: "
            f"disponible {available}, solicitado {requested}"
        )


class ImmutableMovementError(InventoryError):
    """Los movimientos de inventario no pueden modificarse ni eliminarse."""


# --------------------------------------------------------------------------- #
# Utilidades internas
# --------------------------------------------------------------------------- #


_TRUTHY = {"1", "true", "yes", "on"}


def _env_flag(name: str, *, default: bool = False) -> bool:
    """Lee un flag booleano desde el entorno."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUTHY


def _resolve_allow_negative_stock(override: bool | None) -> bool:
    """Prioriza el override explícito sobre el flag global del entorno."""
    if override is not None:
        return override
    return _env_flag("ALLOW_NEGATIVE_STOCK", default=False)


def _commit(db: Session, *, duplicate_message: str) -> None:
    """Confirma la transacción traduciendo violaciones de unicidad."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DuplicateResourceError(duplicate_message) from exc


def _ensure_unique(
    db: Session,
    model: type[Product] | type[Warehouse],
    column: str,
    value: str,
    *,
    label: str,
    exclude_id: int | None = None,
) -> None:
    """Verifica unicidad con un mensaje de error legible."""
    attr = getattr(model, column)
    stmt = select(attr).where(attr == value)
    if exclude_id is not None:
        stmt = stmt.where(model.id != exclude_id)
    if db.execute(stmt.limit(1)).first() is not None:
        raise DuplicateResourceError(f"Ya existe un registro con {label} '{value}'")


def _get_or_create_stock(
    db: Session, *, product_id: int, warehouse_id: int
) -> Stock:
    """Obtiene el saldo con bloqueo de fila, creándolo en 0 si no existe.

    El bloqueo ``FOR UPDATE`` serializa movimientos concurrentes sobre el mismo
    producto/almacén. La creación usa un savepoint para tolerar una carrera con
    otra transacción que haya insertado la fila primero.
    """
    stmt = (
        select(Stock)
        .where(
            Stock.product_id == product_id,
            Stock.warehouse_id == warehouse_id,
        )
        .with_for_update()
    )
    stock = db.execute(stmt).scalar_one_or_none()
    if stock is not None:
        return stock

    try:
        with db.begin_nested():
            stock = Stock(
                product_id=product_id,
                warehouse_id=warehouse_id,
                quantity=0,
            )
            db.add(stock)
    except IntegrityError:
        stock = db.execute(stmt).scalar_one()
    return stock


def _increase(stock: Stock, quantity: int) -> None:
    stock.quantity += quantity


def _decrease(
    stock: Stock,
    quantity: int,
    *,
    allow_negative_stock: bool,
) -> None:
    new_quantity = stock.quantity - quantity
    if new_quantity < 0 and not allow_negative_stock:
        raise InsufficientStockError(
            product_id=stock.product_id,
            warehouse_id=stock.warehouse_id,
            available=stock.quantity,
            requested=quantity,
        )
    stock.quantity = new_quantity


def _validate_movement_shape(data: StockMovementCreate) -> None:
    """Defensa en profundidad de las reglas de bodegas por tipo de movimiento.

    Los esquemas Pydantic ya las validan; se repiten aquí para proteger llamadas
    internas que construyan el payload sin pasar por validación completa.
    """
    source = data.warehouse_source_id
    destination = data.warehouse_destination_id
    movement_type = data.movement_type

    if movement_type == MovementType.TRANSFER:
        if source is None or destination is None:
            raise InvalidMovementError(
                "Una transferencia requiere bodega de origen y de destino"
            )
        if source == destination:
            raise InvalidMovementError(
                "La bodega de origen y la de destino deben ser distintas"
            )
    elif movement_type == MovementType.INBOUND:
        if destination is None or source is not None:
            raise InvalidMovementError(
                "Una entrada (INBOUND) requiere únicamente bodega de destino"
            )
    elif movement_type == MovementType.OUTBOUND:
        if source is None or destination is not None:
            raise InvalidMovementError(
                "Una salida (OUTBOUND) requiere únicamente bodega de origen"
            )
    elif (source is None) == (destination is None):  # ADJUSTMENT
        raise InvalidMovementError(
            "Un ajuste (ADJUSTMENT) requiere exactamente una bodega, "
            "de origen o de destino"
        )


# --------------------------------------------------------------------------- #
# Productos
# --------------------------------------------------------------------------- #


def create_product(db: Session, data: ProductCreate) -> Product:
    """Registra un producto validando la unicidad del SKU (regla 1)."""
    _ensure_unique(db, Product, "sku", data.sku, label="SKU")
    product = Product(**data.model_dump())
    db.add(product)
    _commit(
        db,
        duplicate_message=f"Ya existe un producto con el SKU '{data.sku}'",
    )
    db.refresh(product)
    return product


def get_product(db: Session, product_id: int) -> Product:
    """Obtiene un producto por id o lanza ``ResourceNotFoundError``."""
    product = db.get(Product, product_id)
    if product is None:
        raise ResourceNotFoundError(f"Producto {product_id} no encontrado")
    return product


def list_products(
    db: Session,
    *,
    skip: int = 0,
    limit: int = 100,
    sku: str | None = None,
    name: str | None = None,
    is_active: bool | None = None,
) -> list[Product]:
    """Lista productos con paginación y filtros por SKU o nombre."""
    stmt = select(Product)
    if sku:
        stmt = stmt.where(Product.sku.ilike(f"%{sku}%"))
    if name:
        stmt = stmt.where(Product.name.ilike(f"%{name}%"))
    if is_active is not None:
        stmt = stmt.where(Product.is_active.is_(is_active))
    stmt = stmt.order_by(Product.id).offset(skip).limit(limit)
    return list(db.scalars(stmt).all())


def update_product(db: Session, product_id: int, data: ProductUpdate) -> Product:
    """Actualiza parcialmente un producto respetando la unicidad del SKU."""
    product = get_product(db, product_id)
    changes = data.model_dump(exclude_unset=True)

    new_sku = changes.get("sku")
    if new_sku is not None and new_sku != product.sku:
        _ensure_unique(
            db,
            Product,
            "sku",
            new_sku,
            label="SKU",
            exclude_id=product.id,
        )

    for field, value in changes.items():
        setattr(product, field, value)

    _commit(
        db,
        duplicate_message=f"Ya existe un producto con el SKU '{new_sku}'",
    )
    db.refresh(product)
    return product


# --------------------------------------------------------------------------- #
# Almacenes
# --------------------------------------------------------------------------- #


def create_warehouse(db: Session, data: WarehouseCreate) -> Warehouse:
    """Registra un almacén validando la unicidad de su código."""
    _ensure_unique(db, Warehouse, "code", data.code, label="código")
    warehouse = Warehouse(**data.model_dump())
    db.add(warehouse)
    _commit(
        db,
        duplicate_message=f"Ya existe un almacén con el código '{data.code}'",
    )
    db.refresh(warehouse)
    return warehouse


def get_warehouse(db: Session, warehouse_id: int) -> Warehouse:
    """Obtiene un almacén por id o lanza ``ResourceNotFoundError``."""
    warehouse = db.get(Warehouse, warehouse_id)
    if warehouse is None:
        raise ResourceNotFoundError(f"Almacén {warehouse_id} no encontrado")
    return warehouse


def list_warehouses(
    db: Session,
    *,
    active_only: bool = True,
    skip: int = 0,
    limit: int = 100,
    code: str | None = None,
    name: str | None = None,
) -> list[Warehouse]:
    """Lista almacenes; por defecto solo los activos (contrato de la API)."""
    stmt = select(Warehouse)
    if active_only:
        stmt = stmt.where(Warehouse.is_active.is_(True))
    if code:
        stmt = stmt.where(Warehouse.code.ilike(f"%{code}%"))
    if name:
        stmt = stmt.where(Warehouse.name.ilike(f"%{name}%"))
    stmt = stmt.order_by(Warehouse.id).offset(skip).limit(limit)
    return list(db.scalars(stmt).all())


def update_warehouse(
    db: Session, warehouse_id: int, data: WarehouseUpdate
) -> Warehouse:
    """Actualiza parcialmente un almacén respetando la unicidad del código."""
    warehouse = get_warehouse(db, warehouse_id)
    changes = data.model_dump(exclude_unset=True)

    new_code = changes.get("code")
    if new_code is not None and new_code != warehouse.code:
        _ensure_unique(
            db,
            Warehouse,
            "code",
            new_code,
            label="código",
            exclude_id=warehouse.id,
        )

    for field, value in changes.items():
        setattr(warehouse, field, value)

    _commit(
        db,
        duplicate_message=f"Ya existe un almacén con el código '{new_code}'",
    )
    db.refresh(warehouse)
    return warehouse


# --------------------------------------------------------------------------- #
# Movimientos de stock
# --------------------------------------------------------------------------- #


def create_stock_movement(
    db: Session,
    data: StockMovementCreate,
    *,
    allow_negative_stock: bool | None = None,
) -> StockMovement:
    """Registra un movimiento y actualiza ``Stock`` de forma atómica.

    ``allow_negative_stock`` permite sobrescribir el flag global
    ``ALLOW_NEGATIVE_STOCK`` (útil en pruebas o configuraciones por tenant).
    Si la operación dejaría existencias negativas y el flag está desactivado,
    se lanza ``InsufficientStockError`` y no se persiste nada.
    """
    _validate_movement_shape(data)
    allow_negative = _resolve_allow_negative_stock(allow_negative_stock)

    product = get_product(db, data.product_id)

    source_id = data.warehouse_source_id
    destination_id = data.warehouse_destination_id
    if source_id is not None:
        get_warehouse(db, source_id)
    if destination_id is not None:
        get_warehouse(db, destination_id)

    try:
        if data.movement_type == MovementType.INBOUND:
            stock = _get_or_create_stock(
                db,
                product_id=product.id,
                warehouse_id=destination_id,  # type: ignore[arg-type]
            )
            _increase(stock, data.quantity)

        elif data.movement_type == MovementType.OUTBOUND:
            stock = _get_or_create_stock(
                db,
                product_id=product.id,
                warehouse_id=source_id,  # type: ignore[arg-type]
            )
            _decrease(stock, data.quantity, allow_negative_stock=allow_negative)

        elif data.movement_type == MovementType.TRANSFER:
            # Bloqueo en orden ascendente de bodega para evitar deadlocks entre
            # transferencias simultáneas en sentidos opuestos.
            stocks = {
                warehouse_id: _get_or_create_stock(
                    db, product_id=product.id, warehouse_id=warehouse_id
                )
                for warehouse_id in sorted({source_id, destination_id})
            }
            _decrease(
                stocks[source_id],  # type: ignore[index]
                data.quantity,
                allow_negative_stock=allow_negative,
            )
            _increase(stocks[destination_id], data.quantity)  # type: ignore[index]

        else:  # ADJUSTMENT
            if destination_id is not None:
                stock = _get_or_create_stock(
                    db,
                    product_id=product.id,
                    warehouse_id=destination_id,
                )
                _increase(stock, data.quantity)
            else:
                stock = _get_or_create_stock(
                    db,
                    product_id=product.id,
                    warehouse_id=source_id,  # type: ignore[arg-type]
                )
                _decrease(
                    stock, data.quantity, allow_negative_stock=allow_negative
                )

        movement = StockMovement(**data.model_dump())
        db.add(movement)
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(movement)
    return movement


def list_stock_movements(
    db: Session,
    *,
    skip: int = 0,
    limit: int = 100,
    product_id: int | None = None,
    warehouse_id: int | None = None,
    movement_type: MovementType | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[StockMovement]:
    """Consulta el historial con filtros por producto, bodega, tipo y fechas.

    ``warehouse_id`` coincide tanto con la bodega de origen como con la de
    destino.
    """
    stmt = select(StockMovement)
    if product_id is not None:
        stmt = stmt.where(StockMovement.product_id == product_id)
    if warehouse_id is not None:
        stmt = stmt.where(
            or_(
                StockMovement.warehouse_source_id == warehouse_id,
                StockMovement.warehouse_destination_id == warehouse_id,
            )
        )
    if movement_type is not None:
        stmt = stmt.where(StockMovement.movement_type == movement_type)
    if date_from is not None:
        stmt = stmt.where(StockMovement.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(StockMovement.created_at <= date_to)
    stmt = stmt.order_by(
        StockMovement.created_at.desc(), StockMovement.id.desc()
    ).offset(skip).limit(limit)
    return list(db.scalars(stmt).all())


# --------------------------------------------------------------------------- #
# Inmutabilidad del historial (regla 3)
# --------------------------------------------------------------------------- #


@event.listens_for(StockMovement, "before_update")
def _forbid_movement_update(mapper, connection, target) -> None:  # noqa: ARG001
    raise ImmutableMovementError(
        "Los movimientos de inventario son inmutables: "
        "registre un movimiento ADJUSTMENT para corregir el saldo"
    )


@event.listens_for(StockMovement, "before_delete")
def _forbid_movement_delete(mapper, connection, target) -> None:  # noqa: ARG001
    raise ImmutableMovementError(
        "Los movimientos de inventario no pueden eliminarse: "
        "registre un movimiento ADJUSTMENT para corregir el saldo"
    )
