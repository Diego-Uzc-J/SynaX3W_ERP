"""Servicios de dominio del módulo de Compras y Proveedores.

Implementa la primera capa de reglas de ``specs/purchasing_spec.md``:

* CRUD de ``Supplier`` con unicidad de ``tax_id`` y bloqueo de operaciones
  comerciales con proveedores inactivos (escenario 2 de la spec).
* Alta y edición de ``PurchaseOrder`` únicamente en ``DRAFT``, con generación
  secuencial de códigos ``OC-YYYY-XXXX`` y recálculo automático de subtotales,
  impuestos y total a partir de las líneas.
* Validación estricta de líneas: todo producto incluido debe existir y estar
  activo en ``inventory`` (escenario 7 de la spec).
* Motor transaccional de ``GoodsReceipt``: exige OC ``APPROVED`` o
  ``PARTIALLY_RECEIVED`` y proveedor activo, rechaza sobre-recepciones con 400 y
  registra en un único ``COMMIT`` la recepción, los acumulados de las líneas,
  el cambio de estado de la OC y los movimientos ``INBOUND`` de ``inventory``.
  Las recepciones son inmutables: no se exponen actualizaciones y los
  listeners ORM bloquean cambios o borrados (regla logística del manifiesto).

Las excepciones derivan de ``fastapi.HTTPException`` y declaran su
``status_code`` (400, 404 o 409), por lo que FastAPI las traduce directamente a
respuestas ``{"detail": ...}`` y un futuro router puede registrar un manejador
específico sin cambiar el contrato. El ``status_code`` sigue siendo consultable
para pruebas y capas superiores.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from src.modules.inventory import services as inventory_services
from src.modules.inventory.models import MovementType, Product, Warehouse
from src.modules.inventory.schemas import StockMovementCreate
from src.modules.purchasing.models import (
    GoodsReceipt,
    GoodsReceiptItem,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
    Supplier,
)
from src.modules.purchasing.schemas import (
    GoodsReceiptCreate,
    GoodsReceiptItemCreate,
    PurchaseOrderCreate,
    PurchaseOrderItemCreate,
    PurchaseOrderUpdate,
    SupplierCreate,
    SupplierUpdate,
)

__all__ = [
    "DuplicateResourceError",
    "ImmutableReceiptError",
    "InactiveProductError",
    "InactiveSupplierError",
    "InvalidOrderDataError",
    "InvalidOrderStateError",
    "OverReceiptError",
    "PurchasingServiceError",
    "ResourceNotFoundError",
    "create_goods_receipt",
    "create_purchase_order",
    "create_supplier",
    "deactivate_supplier",
    "ensure_purchase_order_editable",
    "ensure_supplier_active",
    "get_goods_receipt",
    "get_purchase_order",
    "get_supplier",
    "list_goods_receipts",
    "list_purchase_orders",
    "list_suppliers",
    "update_purchase_order",
    "update_supplier",
]

#: Unidad mínima de los importes monetarios del ERP.
_CENT = Decimal("0.01")

#: Límite de ``Numeric(14, 2)`` expresado como Decimal.
_MAX_MONEY = Decimal("999999999999.99")

#: Clave base del advisory lock que serializa la secuencia ``OC-YYYY-XXXX``.
_ORDER_CODE_LOCK_BASE = 8_100_000

#: Clave base del advisory lock que serializa la secuencia ``REC-YYYY-XXXX``.
_RECEIPT_CODE_LOCK_BASE = 8_200_000

#: Estados de una OC que admiten recepciones de mercancía.
_RECEIVABLE_ORDER_STATUSES = frozenset(
    {PurchaseOrderStatus.APPROVED, PurchaseOrderStatus.PARTIALLY_RECEIVED}
)

#: Autor de los movimientos ``INBOUND`` cuando la recepción no indica usuario.
_DEFAULT_RECEIPT_USER = "purchasing"


# --------------------------------------------------------------------------- #
# Excepciones HTTP de dominio
# --------------------------------------------------------------------------- #


class PurchasingServiceError(HTTPException):
    """Error base del módulo de compras con su equivalencia HTTP."""

    status_code: int = 400

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=self.status_code, detail=detail)

    def __str__(self) -> str:
        """Devuelve solo el mensaje, como las excepciones de dominio del ERP."""
        return str(self.detail)


class ResourceNotFoundError(PurchasingServiceError):
    """El recurso solicitado no existe."""

    status_code = 404


class DuplicateResourceError(PurchasingServiceError):
    """Se intentó persistir un valor que debe ser único."""

    status_code = 409


class InactiveSupplierError(PurchasingServiceError):
    """No se pueden emitir documentos a un proveedor inactivo.

    El escenario 2 de ``specs/purchasing_spec.md`` exige explícitamente 400.
    """

    status_code = 400


class InactiveProductError(PurchasingServiceError):
    """Una línea de OC referencia un producto inactivo en inventario.

    El escenario 7 de ``specs/purchasing_spec.md`` exige explícitamente 400.
    """

    status_code = 400


class InvalidOrderStateError(PurchasingServiceError):
    """La edición no es válida para el estado actual de la orden."""

    status_code = 409


class InvalidOrderDataError(PurchasingServiceError):
    """Los datos de la orden no cumplen una regla de negocio."""

    status_code = 400


class OverReceiptError(PurchasingServiceError):
    """La recepción supera la cantidad pendiente de una línea de la OC.

    El escenario 4 de ``specs/purchasing_spec.md`` exige 400 Bad Request.
    """

    status_code = 400

    def __init__(
        self,
        *,
        receipt_code: str,
        purchase_order_item_id: int,
        pending: int,
        requested: int,
    ) -> None:
        self.receipt_code = receipt_code
        self.purchase_order_item_id = purchase_order_item_id
        self.pending = pending
        self.requested = requested
        super().__init__(
            f"Sobre-recepción en {receipt_code}: la línea de orden "
            f"{purchase_order_item_id} tiene {pending} unidades pendientes "
            f"y se intentaron recibir {requested}"
        )


class ImmutableReceiptError(PurchasingServiceError):
    """Una recepción procesada no puede modificarse ni eliminarse.

    El escenario 6 de la spec y la regla de inmutabilidad logística del
    manifiesto exigen conservar la trazabilidad del stock.
    """

    status_code = 400


# --------------------------------------------------------------------------- #
# Utilidades internas
# --------------------------------------------------------------------------- #


def _as_decimal(value: Any) -> Decimal:
    """Convierte valores de SQLAlchemy/SQLite a ``Decimal`` sin perder escala."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _money(value: Any) -> Decimal:
    """Redondea a dos decimales con ``ROUND_HALF_UP``."""
    return _as_decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP)


def _ensure_money_range(value: Decimal, *, label: str) -> None:
    """Valida que un importe quepa en ``Numeric(14, 2)``."""
    if value.copy_abs() > _MAX_MONEY:
        raise InvalidOrderDataError(
            f"El {label} excede el máximo permitido (14,2): {value}"
        )


def _commit(db: Session, *, duplicate_message: str) -> None:
    """Confirma la transacción y traduce violaciones de integridad."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        detail = str(exc.orig).lower()
        if "unique" in detail or "duplicate" in detail:
            raise DuplicateResourceError(duplicate_message) from exc
        raise InvalidOrderDataError(
            "No se pudo guardar el registro por una restricción de integridad"
        ) from exc


def _ensure_unique_tax_id(
    db: Session, tax_id: str, *, exclude_id: int | None = None
) -> None:
    """Verifica que el ``tax_id`` no pertenezca a otro proveedor."""
    stmt = select(Supplier.id).where(Supplier.tax_id == tax_id)
    if exclude_id is not None:
        stmt = stmt.where(Supplier.id != exclude_id)
    if db.execute(stmt.limit(1)).first() is not None:
        raise DuplicateResourceError(
            f"Ya existe un proveedor con el identificador tributario '{tax_id}'"
        )


def _ensure_unique_order_code(
    db: Session, code: str, *, exclude_id: int | None = None
) -> None:
    """Verifica que el código de orden de compra no esté en uso."""
    stmt = select(PurchaseOrder.id).where(PurchaseOrder.code == code)
    if exclude_id is not None:
        stmt = stmt.where(PurchaseOrder.id != exclude_id)
    if db.execute(stmt.limit(1)).first() is not None:
        raise DuplicateResourceError(
            f"Ya existe una orden de compra con el código '{code}'"
        )


def _get_supplier(db: Session, supplier_id: int) -> Supplier:
    """Obtiene un proveedor por id, sin importar su estado."""
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise ResourceNotFoundError(f"Proveedor {supplier_id} no encontrado")
    return supplier


def ensure_supplier_active(
    db: Session, supplier_id: int, *, for_update: bool = False
) -> Supplier:
    """Obtiene un proveedor y exige que esté activo para operar.

    ``for_update=True`` bloquea la fila para serializar comprobaciones
    concurrentes. Se usa al crear o editar órdenes de compra.
    """
    if for_update:
        supplier = db.scalars(
            select(Supplier)
            .where(Supplier.id == supplier_id)
            .with_for_update()
        ).first()
        if supplier is None:
            raise ResourceNotFoundError(f"Proveedor {supplier_id} no encontrado")
    else:
        supplier = _get_supplier(db, supplier_id)

    if not supplier.is_active:
        raise InactiveSupplierError(
            "No se pueden emitir órdenes de compra al proveedor "
            f"{supplier_id} porque está inactivo"
        )
    return supplier


def _validate_dates(issue_date: date, expected_delivery_date: date) -> None:
    """Valida que la entrega estimada no preceda a la emisión."""
    if expected_delivery_date < issue_date:
        raise InvalidOrderDataError(
            "expected_delivery_date no puede ser anterior a issue_date"
        )


def _build_items(
    db: Session, items: Iterable[PurchaseOrderItemCreate]
) -> list[PurchaseOrderItem]:
    """Construye las líneas validando producto activo y calculando subtotales.

    Un producto inexistente responde 404; un producto con
    ``is_active=False`` responde 400, conforme al escenario 7 de la spec.
    """
    built: list[PurchaseOrderItem] = []
    for data in items:
        product = db.get(Product, data.product_id)
        if product is None:
            raise ResourceNotFoundError(f"Producto {data.product_id} no encontrado")
        if not product.is_active:
            raise InactiveProductError(
                f"El producto {data.product_id} ('{product.name}') está inactivo "
                "y no puede incluirse en una orden de compra"
            )

        unit_price = _money(data.unit_price)
        tax_rate = _money(data.tax_rate)
        subtotal = _money(Decimal(data.quantity) * unit_price)
        _ensure_money_range(subtotal, label="subtotal de la línea")

        built.append(
            PurchaseOrderItem(
                product_id=data.product_id,
                quantity=data.quantity,
                unit_price=unit_price,
                tax_rate=tax_rate,
                subtotal=subtotal,
            )
        )

    if not built:
        raise InvalidOrderDataError(
            "La orden de compra debe incluir al menos una línea"
        )
    return built


def _recalculate_totals(
    items: Iterable[PurchaseOrderItem],
) -> tuple[Decimal, Decimal, Decimal]:
    """Calcula ``(subtotal, impuestos, total)`` a partir de las líneas."""
    subtotal = Decimal("0.00")
    tax_amount = Decimal("0.00")

    for item in items:
        line_subtotal = _money(item.subtotal)
        item.subtotal = line_subtotal
        line_tax = _money(
            line_subtotal * _as_decimal(item.tax_rate) / Decimal("100")
        )
        subtotal += line_subtotal
        tax_amount += line_tax

    subtotal = _money(subtotal)
    tax_amount = _money(tax_amount)
    total = _money(subtotal + tax_amount)

    _ensure_money_range(subtotal, label="subtotal de la orden")
    _ensure_money_range(tax_amount, label="importe de impuestos")
    _ensure_money_range(total, label="total de la orden")
    return subtotal, tax_amount, total


def _lock_sequence(db: Session, *, base: int, year: int) -> None:
    """Serializa la generación de códigos en PostgreSQL.

    El advisory lock se libera al terminar la transacción. En SQLite (pruebas)
    no aplica y la unicidad queda garantizada por el índice único de ``code``.
    """
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        db.execute(select(func.pg_advisory_xact_lock(base + year)))


def _next_sequence(db: Session, column: Any, *, prefix: str) -> str:
    """Devuelve el siguiente código ``PREFIJO-XXXX`` para la columna dada."""
    rows = db.scalars(select(column).where(column.like(f"{prefix}%"))).all()

    max_sequence = 0
    for code in rows:
        suffix = code[len(prefix) :]
        if suffix.isdigit():
            max_sequence = max(max_sequence, int(suffix))
    return f"{prefix}{max_sequence + 1:04d}"


def _lock_order_sequence(db: Session, year: int) -> None:
    """Serializa la secuencia de códigos de orden de compra del año."""
    _lock_sequence(db, base=_ORDER_CODE_LOCK_BASE, year=year)


def _next_order_code(db: Session, year: int) -> str:
    """Devuelve el siguiente código ``OC-YYYY-XXXX`` para el año indicado."""
    return _next_sequence(db, PurchaseOrder.code, prefix=f"OC-{year}-")


def _ensure_unique_receipt_code(
    db: Session, code: str, *, exclude_id: int | None = None
) -> None:
    """Verifica que el código de recepción no esté en uso."""
    stmt = select(GoodsReceipt.id).where(GoodsReceipt.code == code)
    if exclude_id is not None:
        stmt = stmt.where(GoodsReceipt.id != exclude_id)
    if db.execute(stmt.limit(1)).first() is not None:
        raise DuplicateResourceError(
            f"Ya existe una recepción con el código '{code}'"
        )


def _lock_receipt_sequence(db: Session, year: int) -> None:
    """Serializa la secuencia de códigos de recepción del año."""
    _lock_sequence(db, base=_RECEIPT_CODE_LOCK_BASE, year=year)


def _next_receipt_code(db: Session, year: int) -> str:
    """Devuelve el siguiente código ``REC-YYYY-XXXX`` para el año indicado."""
    return _next_sequence(db, GoodsReceipt.code, prefix=f"REC-{year}-")


def _get_receivable_order(db: Session, order_id: int) -> PurchaseOrder:
    """Obtiene una OC con líneas y exige un estado que admita recepciones."""
    order = get_purchase_order(db, order_id, for_update=True)
    if order.status not in _RECEIVABLE_ORDER_STATUSES:
        raise InvalidOrderStateError(
            f"La orden de compra '{order.code}' está en estado "
            f"{order.status.value}; solo se pueden recibir órdenes APPROVED "
            "o PARTIALLY_RECEIVED"
        )
    return order


def _get_receipt_warehouse(db: Session, warehouse_id: int) -> Warehouse:
    """Obtiene la bodega destino traduciendo el error de inventario a 404."""
    try:
        return inventory_services.get_warehouse(db, warehouse_id)
    except inventory_services.ResourceNotFoundError as exc:
        raise ResourceNotFoundError(str(exc)) from exc


def _validate_receipt_lines(
    *,
    receipt_code: str,
    order: PurchaseOrder,
    data: GoodsReceiptCreate,
) -> list[tuple[PurchaseOrderItem, GoodsReceiptItemCreate]]:
    """Valida pertenencia y sobre-recepción de cada línea.

    Devuelve pares ``(línea de OC, línea de recepción)`` ya validados. Toda
    comprobación ocurre antes de escribir en la base de datos, de modo que un
    rechazo no deja recepciones parciales ni movimientos de stock huérfanos.
    """
    order_items = {item.id: item for item in order.items}
    seen: set[int] = set()
    validated: list[tuple[PurchaseOrderItem, GoodsReceiptItemCreate]] = []

    for line in data.items:
        if line.purchase_order_item_id in seen:
            raise InvalidOrderDataError(
                "No se puede recibir dos veces la misma línea de orden "
                "en una sola recepción"
            )
        seen.add(line.purchase_order_item_id)

        order_item = order_items.get(line.purchase_order_item_id)
        if order_item is None:
            raise InvalidOrderDataError(
                f"La línea {line.purchase_order_item_id} no pertenece a la "
                f"orden de compra '{order.code}'"
            )

        pending = order_item.quantity - order_item.received_quantity
        if line.quantity > pending:
            raise OverReceiptError(
                receipt_code=receipt_code,
                purchase_order_item_id=order_item.id,
                pending=pending,
                requested=line.quantity,
            )
        validated.append((order_item, line))

    if not validated:
        raise InvalidOrderDataError("La recepción debe incluir al menos una línea")
    return validated


# --------------------------------------------------------------------------- #
# Proveedores — /api/v1/purchasing/suppliers
# --------------------------------------------------------------------------- #


def create_supplier(db: Session, data: SupplierCreate) -> Supplier:
    """Registra un proveedor validando la unicidad de su ``tax_id``."""
    _ensure_unique_tax_id(db, data.tax_id)
    supplier = Supplier(**data.model_dump())
    db.add(supplier)
    _commit(
        db,
        duplicate_message=(
            "Ya existe un proveedor con el identificador tributario "
            f"'{data.tax_id}'"
        ),
    )
    db.refresh(supplier)
    return supplier


def get_supplier(db: Session, supplier_id: int) -> Supplier:
    """Obtiene un proveedor por id o lanza ``ResourceNotFoundError``."""
    return _get_supplier(db, supplier_id)


def list_suppliers(
    db: Session,
    *,
    skip: int = 0,
    limit: int = 100,
    company_name: str | None = None,
    tax_id: str | None = None,
    is_active: bool | None = None,
) -> list[Supplier]:
    """Lista proveedores con paginación y filtros por razón social o estado."""
    stmt = select(Supplier)
    if company_name:
        stmt = stmt.where(Supplier.company_name.ilike(f"%{company_name}%"))
    if tax_id:
        stmt = stmt.where(Supplier.tax_id.ilike(f"%{tax_id}%"))
    if is_active is not None:
        stmt = stmt.where(Supplier.is_active.is_(is_active))
    stmt = stmt.order_by(Supplier.id).offset(skip).limit(limit)
    return list(db.scalars(stmt).all())


def update_supplier(
    db: Session, supplier_id: int, data: SupplierUpdate
) -> Supplier:
    """Actualiza parcialmente un proveedor respetando la unicidad del ``tax_id``.

    Se permite editar proveedores inactivos para poder reactivarlos mediante
    ``is_active=True``; las operaciones comerciales siguen bloqueadas mientras
    el proveedor permanezca inactivo.
    """
    supplier = _get_supplier(db, supplier_id)
    changes = data.model_dump(exclude_unset=True)

    new_tax_id = changes.get("tax_id")
    if new_tax_id is not None and new_tax_id != supplier.tax_id:
        _ensure_unique_tax_id(db, new_tax_id, exclude_id=supplier.id)

    for field, value in changes.items():
        setattr(supplier, field, value)

    _commit(
        db,
        duplicate_message=(
            "Ya existe un proveedor con el identificador tributario "
            f"'{new_tax_id or supplier.tax_id}'"
        ),
    )
    db.refresh(supplier)
    return supplier


def deactivate_supplier(db: Session, supplier_id: int) -> Supplier:
    """Desactiva un proveedor (borrado lógico) preservando su historial.

    No se elimina la fila porque las órdenes y facturas la referencian con
    ``ON DELETE RESTRICT``.
    """
    supplier = _get_supplier(db, supplier_id)
    if supplier.is_active:
        supplier.is_active = False
        db.commit()
        db.refresh(supplier)
    return supplier


# --------------------------------------------------------------------------- #
# Órdenes de compra — /api/v1/purchasing/orders
# --------------------------------------------------------------------------- #


def create_purchase_order(
    db: Session, data: PurchaseOrderCreate
) -> PurchaseOrder:
    """Crea una orden de compra en ``DRAFT`` con totales calculados.

    Si ``data.code`` se omite, se genera un código secuencial ``OC-YYYY-XXXX``.
    Un código explícito duplicado se rechaza con 409. El proveedor debe estar
    activo (400) y todas las líneas deben referenciar productos activos (400).
    """
    ensure_supplier_active(db, data.supplier_id, for_update=True)
    _validate_dates(data.issue_date, data.expected_delivery_date)
    items = _build_items(db, data.items)
    subtotal, tax_amount, total = _recalculate_totals(items)

    if data.code is None:
        _lock_order_sequence(db, data.issue_date.year)
        code = _next_order_code(db, data.issue_date.year)
    else:
        code = data.code
        _ensure_unique_order_code(db, code)

    order = PurchaseOrder(
        code=code,
        supplier_id=data.supplier_id,
        status=PurchaseOrderStatus.DRAFT,
        issue_date=data.issue_date,
        expected_delivery_date=data.expected_delivery_date,
        subtotal=subtotal,
        tax_amount=tax_amount,
        total=total,
    )
    order.items = items
    db.add(order)

    _commit(
        db,
        duplicate_message=f"Ya existe una orden de compra con el código '{code}'",
    )
    db.refresh(order)
    return order


def get_purchase_order(
    db: Session, order_id: int, *, for_update: bool = False
) -> PurchaseOrder:
    """Obtiene una OC con sus líneas o lanza ``ResourceNotFoundError``."""
    stmt = (
        select(PurchaseOrder)
        .where(PurchaseOrder.id == order_id)
        .options(selectinload(PurchaseOrder.items))
    )
    if for_update:
        stmt = stmt.with_for_update()
    order = db.scalars(stmt).first()
    if order is None:
        raise ResourceNotFoundError(f"Orden de compra {order_id} no encontrada")
    return order


def list_purchase_orders(
    db: Session,
    *,
    skip: int = 0,
    limit: int = 100,
    status: PurchaseOrderStatus | None = None,
    supplier_id: int | None = None,
    code: str | None = None,
) -> list[PurchaseOrder]:
    """Lista órdenes con filtros por estado, proveedor o código."""
    stmt = select(PurchaseOrder).options(selectinload(PurchaseOrder.items))
    if status is not None:
        stmt = stmt.where(PurchaseOrder.status == status)
    if supplier_id is not None:
        stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
    if code:
        stmt = stmt.where(PurchaseOrder.code.ilike(f"%{code}%"))
    stmt = stmt.order_by(PurchaseOrder.id).offset(skip).limit(limit)
    return list(db.scalars(stmt).all())


def ensure_purchase_order_editable(order: PurchaseOrder) -> None:
    """Exige que la OC esté en ``DRAFT`` para poder editarla.

    La regla 1 de la spec declara inmutables las líneas una vez la orden pasa a
    ``APPROVED`` o ``SENT``; en este hito solo se edita en borrador.
    """
    if order.status is not PurchaseOrderStatus.DRAFT:
        raise InvalidOrderStateError(
            f"La orden de compra '{order.code}' está en estado "
            f"{order.status.value} y solo puede editarse en DRAFT"
        )


def update_purchase_order(
    db: Session, order_id: int, data: PurchaseOrderUpdate
) -> PurchaseOrder:
    """Edita una OC mientras permanezca en ``DRAFT``.

    Si se envían ``items``, sustituyen a todas las líneas anteriores y los
    totales se recalculan. El ``code`` es inmutable. El proveedor actual y el
    nuevo (si cambia) deben estar activos.
    """
    order = get_purchase_order(db, order_id)
    ensure_purchase_order_editable(order)

    ensure_supplier_active(db, order.supplier_id)
    changes = data.model_dump(exclude_unset=True, exclude={"items"})

    new_supplier_id = changes.get("supplier_id")
    if new_supplier_id is not None and new_supplier_id != order.supplier_id:
        ensure_supplier_active(db, new_supplier_id)

    issue_date = changes.get("issue_date", order.issue_date)
    expected = changes.get("expected_delivery_date", order.expected_delivery_date)
    _validate_dates(issue_date, expected)

    if "items" in data.model_fields_set:
        # ``model_dump`` convertiría las líneas en dicts; se usan los esquemas
        # originales para conservar sus validadores y tipos Decimal.
        assert data.items is not None
        new_items = _build_items(db, data.items)
        subtotal, tax_amount, total = _recalculate_totals(new_items)
        order.items.clear()
        order.items.extend(new_items)
        order.subtotal = subtotal
        order.tax_amount = tax_amount
        order.total = total

    for field in ("supplier_id", "issue_date", "expected_delivery_date"):
        if field in changes:
            setattr(order, field, changes[field])

    _commit(
        db,
        duplicate_message=(
            f"Ya existe una orden de compra con el código '{order.code}'"
        ),
    )
    db.refresh(order)
    return order


# --------------------------------------------------------------------------- #
# Recepción de mercancía — /api/v1/purchasing/receipts
# --------------------------------------------------------------------------- #


def create_goods_receipt(
    db: Session, receipt_data: GoodsReceiptCreate
) -> GoodsReceipt:
    """Registra una recepción y actualiza el stock en una transacción ACID.

    Precondiciones (todas comprobadas antes de escribir):

    * la OC existe, está ``APPROVED`` o ``PARTIALLY_RECEIVED`` y su proveedor
      sigue activo;
    * la bodega destino existe en ``inventory``;
    * cada línea pertenece a la OC y no supere su cantidad pendiente.

    En el mismo ``COMMIT`` se insertan ``GoodsReceipt`` y sus líneas, se
    incrementa ``received_quantity``, se ajusta el estado de la OC a
    ``PARTIALLY_RECEIVED`` o ``COMPLETED`` y se registran los movimientos
    ``INBOUND`` mediante ``inventory_services.create_stock_movement`` con
    ``commit=False``. Cualquier fallo revierte el conjunto completo.
    """
    order = _get_receivable_order(db, receipt_data.purchase_order_id)
    ensure_supplier_active(db, order.supplier_id)
    # La existencia de la bodega se valida aquí para devolver un 404 de compras
    # con mensaje claro antes de escribir; el servicio de inventory la valida
    # de nuevo al crear cada movimiento.
    _get_receipt_warehouse(db, receipt_data.warehouse_id)

    if receipt_data.code is None:
        _lock_receipt_sequence(db, receipt_data.receipt_date.year)
        code = _next_receipt_code(db, receipt_data.receipt_date.year)
    else:
        code = receipt_data.code
        _ensure_unique_receipt_code(db, code)

    validated = _validate_receipt_lines(
        receipt_code=code, order=order, data=receipt_data
    )

    receipt = GoodsReceipt(
        code=code,
        purchase_order_id=order.id,
        warehouse_id=receipt_data.warehouse_id,
        receipt_date=receipt_data.receipt_date,
        received_by=receipt_data.received_by,
        notes=receipt_data.notes,
    )
    db.add(receipt)

    for order_item, line in validated:
        receipt.items.append(
            GoodsReceiptItem(
                purchase_order_item_id=order_item.id,
                quantity=line.quantity,
            )
        )
        order_item.received_quantity += line.quantity

    if all(item.received_quantity >= item.quantity for item in order.items):
        order.status = PurchaseOrderStatus.COMPLETED
    else:
        order.status = PurchaseOrderStatus.PARTIALLY_RECEIVED

    try:
        for order_item, line in validated:
            movement = StockMovementCreate(
                product_id=order_item.product_id,
                warehouse_destination_id=receipt_data.warehouse_id,
                movement_type=MovementType.INBOUND,
                quantity=line.quantity,
                reference_document=code,
                notes=(
                    receipt_data.notes
                    or f"Recepción {code} de la OC {order.code}"
                ),
                created_by=receipt_data.received_by or _DEFAULT_RECEIPT_USER,
            )
            inventory_services.create_stock_movement(db, movement, commit=False)

        _commit(
            db,
            duplicate_message=f"Ya existe una recepción con el código '{code}'",
        )
    except Exception:
        # Un movimiento, saldo, acumulado o cambio de estado que falle revierte
        # también la recepción y las líneas ya añadidas a la sesión.
        db.rollback()
        raise

    db.refresh(receipt)
    return receipt


def get_goods_receipt(db: Session, receipt_id: int) -> GoodsReceipt:
    """Obtiene una recepción con sus líneas o lanza ``ResourceNotFoundError``."""
    stmt = (
        select(GoodsReceipt)
        .where(GoodsReceipt.id == receipt_id)
        .options(selectinload(GoodsReceipt.items))
    )
    receipt = db.scalars(stmt).first()
    if receipt is None:
        raise ResourceNotFoundError(f"Recepción {receipt_id} no encontrada")
    return receipt


def list_goods_receipts(
    db: Session,
    *,
    skip: int = 0,
    limit: int = 100,
    purchase_order_id: int | None = None,
    warehouse_id: int | None = None,
) -> list[GoodsReceipt]:
    """Lista recepciones con filtros por OC o bodega destino."""
    stmt = select(GoodsReceipt).options(selectinload(GoodsReceipt.items))
    if purchase_order_id is not None:
        stmt = stmt.where(GoodsReceipt.purchase_order_id == purchase_order_id)
    if warehouse_id is not None:
        stmt = stmt.where(GoodsReceipt.warehouse_id == warehouse_id)
    stmt = stmt.order_by(GoodsReceipt.id).offset(skip).limit(limit)
    return list(db.scalars(stmt).all())


# --------------------------------------------------------------------------- #
# Inmutabilidad logística (manifiesto, sección 4 y escenario 6 de la spec)
# --------------------------------------------------------------------------- #


@event.listens_for(GoodsReceipt, "before_update")
def _forbid_receipt_update(mapper, connection, target) -> None:  # noqa: ARG001
    raise ImmutableReceiptError(
        "Las recepciones de mercancía son inmutables: ya impactaron el stock; "
        "registre un movimiento ADJUSTMENT para corregir el saldo"
    )


@event.listens_for(GoodsReceipt, "before_delete")
def _forbid_receipt_delete(mapper, connection, target) -> None:  # noqa: ARG001
    raise ImmutableReceiptError(
        "Las recepciones de mercancía no pueden eliminarse: conserve la "
        "trazabilidad del inventario"
    )


@event.listens_for(GoodsReceiptItem, "before_update")
def _forbid_receipt_item_update(mapper, connection, target) -> None:  # noqa: ARG001
    raise ImmutableReceiptError(
        "Las líneas de recepción son inmutables una vez registradas"
    )


@event.listens_for(GoodsReceiptItem, "before_delete")
def _forbid_receipt_item_delete(mapper, connection, target) -> None:  # noqa: ARG001
    raise ImmutableReceiptError(
        "Las líneas de recepción no pueden eliminarse: conserve la trazabilidad"
    )
