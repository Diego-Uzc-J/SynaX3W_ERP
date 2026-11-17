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
* Cuentas por pagar: registro de ``SupplierBill`` contrastado con los costos
  pactados y las cantidades recibidas (regla 6), abonos con historial inmutable
  y transiciones de OC (aprobación, cancelación y cierre forzoso).

Las excepciones derivan de ``fastapi.HTTPException`` y declaran su
``status_code`` (400, 404 o 409), por lo que FastAPI las traduce directamente a
respuestas ``{"detail": ...}`` y un futuro router puede registrar un manejador
específico sin cambiar el contrato. El ``status_code`` sigue siendo consultable
para pruebas y capas superiores.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import event, func, inspect, select
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
    SupplierBill,
    SupplierBillPayment,
    SupplierBillStatus,
)
from src.modules.purchasing.schemas import (
    GoodsReceiptCreate,
    GoodsReceiptItemCreate,
    PurchaseOrderCreate,
    PurchaseOrderItemCreate,
    PurchaseOrderUpdate,
    SupplierBillCreate,
    SupplierBillPaymentCreate,
    SupplierCreate,
    SupplierUpdate,
)

__all__ = [
    "DuplicateResourceError",
    "ImmutableBillError",
    "ImmutableReceiptError",
    "InactiveProductError",
    "InactiveSupplierError",
    "InvalidBillError",
    "InvalidBillStateError",
    "InvalidOrderDataError",
    "InvalidOrderStateError",
    "OverReceiptError",
    "PurchasingServiceError",
    "ResourceNotFoundError",
    "approve_purchase_order",
    "cancel_purchase_order",
    "create_goods_receipt",
    "create_purchase_order",
    "create_supplier",
    "create_supplier_bill",
    "deactivate_supplier",
    "ensure_purchase_order_editable",
    "ensure_supplier_active",
    "force_close_purchase_order",
    "get_goods_receipt",
    "get_purchase_order",
    "get_supplier",
    "get_supplier_bill",
    "list_bill_payments",
    "list_goods_receipts",
    "list_purchase_orders",
    "list_supplier_bills",
    "list_suppliers",
    "register_bill_payment",
    "reject_bill_mutation",
    "update_purchase_order",
    "update_supplier",
    "void_supplier_bill",
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

#: Clave base del advisory lock que serializa la secuencia ``BILL-YYYY-XXXX``.
_BILL_CODE_LOCK_BASE = 8_300_000

#: Tolerancia de un centavo al contrastar importes monetarios.
_MONEY_EPSILON = Decimal("0.01")

#: Únicos campos que una cuenta por pagar puede cambiar: los abonos actualizan
#: el saldo y el estado; el resto del documento es inmutable (manifiesto §4).
_BILL_MUTABLE_FIELDS = frozenset({"balance_due", "status"})


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


class InvalidBillError(PurchasingServiceError):
    """La factura no guarda consistencia con la OC y las cantidades recibidas.

    Materializa la regla de negocio 6 de ``specs/purchasing_spec.md``.
    """

    status_code = 400


class InvalidBillStateError(PurchasingServiceError):
    """La operación no es válida para el estado actual de la factura."""

    status_code = 409


class ImmutableBillError(PurchasingServiceError):
    """Un documento financiero registrado no puede alterarse ni borrarse.

    La inmutabilidad financiera del manifiesto (sección 4) solo permite
    contrapartidas: abonos nuevos, anulación o nota de crédito.
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
# Cuentas por pagar — helpers (regla de negocio 6)
# --------------------------------------------------------------------------- #


def _get_bill(db: Session, bill_id: int, *, for_update: bool = False) -> SupplierBill:
    """Obtiene una cuenta por pagar o lanza ``ResourceNotFoundError``."""
    stmt = select(SupplierBill)
    if for_update:
        stmt = stmt.with_for_update()
    bill = db.scalars(stmt.where(SupplierBill.id == bill_id)).first()
    if bill is None:
        raise ResourceNotFoundError(f"Factura de proveedor {bill_id} no encontrada")
    return bill


def _ensure_unique_bill_code(
    db: Session, code: str, *, exclude_id: int | None = None
) -> None:
    """Verifica que el código de cuenta por pagar no esté en uso."""
    stmt = select(SupplierBill.id).where(SupplierBill.code == code)
    if exclude_id is not None:
        stmt = stmt.where(SupplierBill.id != exclude_id)
    if db.execute(stmt.limit(1)).first() is not None:
        raise DuplicateResourceError(
            f"Ya existe una factura de proveedor con el código '{code}'"
        )


def _ensure_unique_supplier_invoice_number(
    db: Session, supplier_id: int, invoice_number: str
) -> None:
    """Evita registrar dos veces la misma factura física de un proveedor."""
    stmt = select(SupplierBill.id).where(
        SupplierBill.supplier_id == supplier_id,
        SupplierBill.supplier_invoice_number == invoice_number,
    )
    if db.execute(stmt.limit(1)).first() is not None:
        raise DuplicateResourceError(
            "Ya existe una factura registrada con el número "
            f"'{invoice_number}' para el proveedor {supplier_id}"
        )


def _lock_bill_sequence(db: Session, year: int) -> None:
    """Serializa la secuencia de códigos de factura del año."""
    _lock_sequence(db, base=_BILL_CODE_LOCK_BASE, year=year)


def _next_bill_code(db: Session, year: int) -> str:
    """Devuelve el siguiente código ``BILL-YYYY-XXXX`` para el año indicado."""
    return _next_sequence(db, SupplierBill.code, prefix=f"BILL-{year}-")


def _bill_source(
    db: Session, data: SupplierBillCreate
) -> tuple[PurchaseOrder, GoodsReceipt | None]:
    """Resuelve la OC y la recepción de origen, verificando que concuerden."""
    receipt: GoodsReceipt | None = None
    if data.goods_receipt_id is not None:
        receipt = get_goods_receipt(db, data.goods_receipt_id)
        order = get_purchase_order(db, receipt.purchase_order_id)
        if (
            data.purchase_order_id is not None
            and data.purchase_order_id != order.id
        ):
            raise InvalidBillError(
                "La recepción indicada no pertenece a la orden de compra "
                f"{data.purchase_order_id}"
            )
    else:
        assert data.purchase_order_id is not None  # validado por el esquema
        order = get_purchase_order(db, data.purchase_order_id)
    return order, receipt


def _expected_bill_amounts(
    order: PurchaseOrder, receipt: GoodsReceipt | None
) -> tuple[Decimal, Decimal, Decimal]:
    """Calcula los importes facturables a partir de costos y cantidades reales.

    Si se factura contra una recepción, solo cuentan las líneas de esa
    recepción; si se factura contra la OC, cuentan las cantidades acumuladas
    ``received_quantity`` de todas sus líneas.
    """
    received_by_line: dict[int, int] = {}
    if receipt is not None:
        for item in receipt.items:
            key = item.purchase_order_item_id
            received_by_line[key] = received_by_line.get(key, 0) + item.quantity

    subtotal = Decimal("0.00")
    tax_amount = Decimal("0.00")
    for item in order.items:
        quantity = (
            received_by_line.get(item.id, 0)
            if receipt is not None
            else item.received_quantity
        )
        if quantity <= 0:
            continue
        line_subtotal = _money(Decimal(quantity) * _as_decimal(item.unit_price))
        line_tax = _money(
            line_subtotal * _as_decimal(item.tax_rate) / Decimal("100")
        )
        subtotal += line_subtotal
        tax_amount += line_tax

    subtotal = _money(subtotal)
    tax_amount = _money(tax_amount)
    return subtotal, tax_amount, _money(subtotal + tax_amount)


def _billed_amounts(
    db: Session,
    *,
    order_id: int,
    receipt_id: int | None = None,
) -> tuple[Decimal, Decimal]:
    """Devuelve ``(subtotal, impuestos)`` ya facturados y no anulados."""
    stmt = select(SupplierBill.subtotal, SupplierBill.tax_amount).where(
        SupplierBill.purchase_order_id == order_id,
        SupplierBill.status != SupplierBillStatus.VOID,
    )
    if receipt_id is not None:
        stmt = stmt.where(SupplierBill.goods_receipt_id == receipt_id)
    subtotal = Decimal("0.00")
    tax_amount = Decimal("0.00")
    for billed_subtotal, billed_tax in db.execute(stmt).all():
        subtotal += _as_decimal(billed_subtotal)
        tax_amount += _as_decimal(billed_tax)
    return _money(subtotal), _money(tax_amount)


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
# Transiciones de la OC — /api/v1/purchasing/orders/{id}/...
# --------------------------------------------------------------------------- #


def approve_purchase_order(
    db: Session, order_id: int, *, send: bool = False
) -> PurchaseOrder:
    """Aprueba (o envía) una OC en ``DRAFT``; otros estados responden 409.

    ``send=True`` deja la orden en ``SENT`` para reflejar que fue remitida al
    proveedor antes de su aprobación formal; ambos estados son válidos como
    punto de partida de la recepción según el contrato de la spec.
    """
    order = get_purchase_order(db, order_id, for_update=True)
    if order.status is not PurchaseOrderStatus.DRAFT:
        raise InvalidOrderStateError(
            f"La orden de compra '{order.code}' está en estado "
            f"{order.status.value}; solo se puede aprobar desde DRAFT"
        )
    order.status = (
        PurchaseOrderStatus.SENT if send else PurchaseOrderStatus.APPROVED
    )
    _commit(
        db,
        duplicate_message=f"Conflicto al aprobar la orden '{order.code}'",
    )
    db.refresh(order)
    return order


def cancel_purchase_order(
    db: Session, order_id: int, *, reason: str | None = None
) -> PurchaseOrder:
    """Cancela una OC sin movimientos de inventario asociados.

    El escenario 5 de la spec exige 400 cuando la orden ya registró recepciones
    parciales. La cancelación es idempotente. ``reason`` se acepta por simetría
    con la API, pero el modelo no persiste motivos (no existe campo en la spec).
    """
    del reason  # documentado arriba: no hay columna de motivo en el modelo
    order = get_purchase_order(db, order_id, for_update=True)
    if order.status is PurchaseOrderStatus.CANCELLED:
        return order

    has_receipts = (
        db.scalars(
            select(GoodsReceipt.id)
            .where(GoodsReceipt.purchase_order_id == order.id)
            .limit(1)
        ).first()
        is not None
    )
    if has_receipts or order.status in {
        PurchaseOrderStatus.PARTIALLY_RECEIVED,
        PurchaseOrderStatus.COMPLETED,
    }:
        raise InvalidOrderDataError(
            f"No se puede cancelar la orden '{order.code}' porque ya tiene "
            "movimientos de inventario asociados; use FORCE_CLOSED"
        )

    order.status = PurchaseOrderStatus.CANCELLED
    _commit(
        db,
        duplicate_message=f"Conflicto al cancelar la orden '{order.code}'",
    )
    db.refresh(order)
    return order


def force_close_purchase_order(db: Session, order_id: int) -> PurchaseOrder:
    """Cierra forzosamente una OC aprobada para liberar saldos pendientes."""
    order = get_purchase_order(db, order_id, for_update=True)
    if order.status not in {
        PurchaseOrderStatus.APPROVED,
        PurchaseOrderStatus.PARTIALLY_RECEIVED,
    }:
        raise InvalidOrderStateError(
            f"La orden de compra '{order.code}' está en estado "
            f"{order.status.value}; solo se puede forzar el cierre desde "
            "APPROVED o PARTIALLY_RECEIVED"
        )
    order.status = PurchaseOrderStatus.FORCE_CLOSED
    _commit(
        db,
        duplicate_message=f"Conflicto al cerrar la orden '{order.code}'",
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


# --------------------------------------------------------------------------- #
# Cuentas por pagar — /api/v1/purchasing/bills
# --------------------------------------------------------------------------- #


def create_supplier_bill(db: Session, data: SupplierBillCreate) -> SupplierBill:
    """Registra una factura verificando costos pactados y cantidades recibidas.

    La regla 6 de la spec se aplica en tres niveles:

    1. la factura debe vincularse a una OC válida y, si indica recepción, esta
       debe pertenecer a esa OC y el proveedor debe ser el mismo;
    2. el subtotal y los impuestos se contrastan con ``unit_price``, ``tax_rate``
       y las cantidades físicamente recibidas (de la recepción o acumuladas en
       la OC), respetando la tasa impositiva ponderada;
    3. no se puede facturar más de lo pendiente: se descuentan las facturas
       anteriores no anuladas que usen el mismo documento de origen.

    Importes como ``total`` o ``balance_due`` enviados por el cliente se
    ignoran: siempre se derivan de ``subtotal`` e impuestos validados.
    """
    supplier = _get_supplier(db, data.supplier_id)
    _ensure_unique_supplier_invoice_number(
        db, supplier.id, data.supplier_invoice_number
    )
    order, receipt = _bill_source(db, data)
    if order.supplier_id != supplier.id:
        raise InvalidBillError(
            f"La orden '{order.code}' pertenece al proveedor {order.supplier_id}, "
            f"no al proveedor {supplier.id} indicado en la factura"
        )

    expected_subtotal, expected_tax, _ = _expected_bill_amounts(order, receipt)
    if expected_subtotal <= 0:
        raise InvalidBillError(
            "No hay cantidades recibidas para facturar en el documento de origen"
        )

    billed_subtotal, billed_tax = _billed_amounts(db, order_id=order.id)
    remaining_subtotal = _money(expected_subtotal - billed_subtotal)
    remaining_tax = _money(expected_tax - billed_tax)
    if receipt is not None:
        receipt_subtotal, receipt_tax = _billed_amounts(
            db, order_id=order.id, receipt_id=receipt.id
        )
        remaining_subtotal = min(
            remaining_subtotal, _money(expected_subtotal - receipt_subtotal)
        )
        remaining_tax = min(remaining_tax, _money(expected_tax - receipt_tax))
    remaining_subtotal = max(Decimal("0.00"), remaining_subtotal)
    remaining_tax = max(Decimal("0.00"), remaining_tax)

    subtotal = _money(data.subtotal)
    tax_amount = _money(data.tax_amount)
    if subtotal <= 0:
        raise InvalidBillError("El subtotal facturado debe ser mayor que cero")
    if (
        subtotal > remaining_subtotal + _MONEY_EPSILON
        or tax_amount > remaining_tax + _MONEY_EPSILON
    ):
        raise InvalidBillError(
            "La factura excede lo pendiente de facturar: máximo "
            f"subtotal {remaining_subtotal} e impuestos {remaining_tax} "
            f"(recibido: subtotal {subtotal}, impuestos {tax_amount})"
        )

    expected_tax_for_subtotal = _money(
        subtotal * expected_tax / expected_subtotal
    )
    if abs(tax_amount - expected_tax_for_subtotal) > _MONEY_EPSILON:
        raise InvalidBillError(
            f"Los impuestos {tax_amount} no coinciden con la tasa pactada; "
            f"para un subtotal de {subtotal} deberían ser "
            f"{expected_tax_for_subtotal}"
        )

    total = _money(subtotal + tax_amount)

    if data.code is None:
        _lock_bill_sequence(db, data.issue_date.year)
        code = _next_bill_code(db, data.issue_date.year)
    else:
        code = data.code
        _ensure_unique_bill_code(db, code)

    due_date = data.due_date
    if due_date is None:
        due_date = data.issue_date + timedelta(days=supplier.payment_terms_days)

    bill = SupplierBill(
        code=code,
        supplier_id=supplier.id,
        purchase_order_id=order.id,
        goods_receipt_id=receipt.id if receipt is not None else None,
        supplier_invoice_number=data.supplier_invoice_number,
        status=SupplierBillStatus.PENDING,
        issue_date=data.issue_date,
        due_date=due_date,
        subtotal=subtotal,
        tax_amount=tax_amount,
        total=total,
        balance_due=total,
    )
    db.add(bill)
    _commit(
        db,
        duplicate_message=f"Ya existe una factura de proveedor con el código '{code}'",
    )
    db.refresh(bill)
    return bill


def get_supplier_bill(db: Session, bill_id: int) -> SupplierBill:
    """Obtiene una cuenta por pagar o lanza ``ResourceNotFoundError``."""
    return _get_bill(db, bill_id)


def list_supplier_bills(
    db: Session,
    *,
    skip: int = 0,
    limit: int = 100,
    status: SupplierBillStatus | None = None,
    supplier_id: int | None = None,
    purchase_order_id: int | None = None,
    goods_receipt_id: int | None = None,
    code: str | None = None,
) -> list[SupplierBill]:
    """Lista facturas con filtros por estado, proveedor y documento origen."""
    stmt = select(SupplierBill)
    if status is not None:
        stmt = stmt.where(SupplierBill.status == status)
    if supplier_id is not None:
        stmt = stmt.where(SupplierBill.supplier_id == supplier_id)
    if purchase_order_id is not None:
        stmt = stmt.where(SupplierBill.purchase_order_id == purchase_order_id)
    if goods_receipt_id is not None:
        stmt = stmt.where(SupplierBill.goods_receipt_id == goods_receipt_id)
    if code:
        stmt = stmt.where(SupplierBill.code.ilike(f"%{code}%"))
    stmt = stmt.order_by(SupplierBill.id).offset(skip).limit(limit)
    return list(db.scalars(stmt).all())


def register_bill_payment(
    db: Session, bill_id: int, data: SupplierBillPaymentCreate
) -> SupplierBill:
    """Aplica un abono y actualiza ``balance_due``/estado en un único ``COMMIT``.

    No se admiten pagos sobre facturas ``PAID`` o ``VOID`` ni importes mayores
    al saldo. Cada abono queda en ``supplier_bill_payments`` como documento
    inmutable, junto con el saldo resultante.
    """
    bill = _get_bill(db, bill_id, for_update=True)
    if bill.status in {SupplierBillStatus.PAID, SupplierBillStatus.VOID}:
        code = bill.code
        db.rollback()
        raise InvalidBillStateError(
            f"La factura '{code}' está en estado {bill.status.value} y no "
            "admite pagos"
        )

    amount = _money(data.amount)
    balance = _money(bill.balance_due)
    if amount > balance:
        code = bill.code
        db.rollback()
        raise InvalidBillError(
            f"El pago ({amount}) excede el saldo pendiente de la factura "
            f"'{code}' ({balance})"
        )

    bill.balance_due = _money(balance - amount)
    bill.status = (
        SupplierBillStatus.PAID
        if bill.balance_due == 0
        else SupplierBillStatus.PARTIALLY_PAID
    )
    db.add(
        SupplierBillPayment(
            bill_id=bill.id,
            amount=amount,
            paid_at=data.paid_at,
            reference=data.reference,
        )
    )
    _commit(
        db,
        duplicate_message=f"Conflicto al registrar el pago de '{bill.code}'",
    )
    db.refresh(bill)
    return bill


def list_bill_payments(
    db: Session,
    *,
    bill_id: int,
    skip: int = 0,
    limit: int = 100,
) -> list[SupplierBillPayment]:
    """Devuelve el historial de abonos de una factura, del primero al último."""
    get_supplier_bill(db, bill_id)
    stmt = (
        select(SupplierBillPayment)
        .where(SupplierBillPayment.bill_id == bill_id)
        .order_by(SupplierBillPayment.id)
        .offset(skip)
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def void_supplier_bill(db: Session, bill_id: int) -> SupplierBill:
    """Anula una factura ``PENDING`` sin pagos; es idempotente si ya está VOID.

    Una factura con abonos exige una contrapartida formal en lugar de borrar el
    historial, de acuerdo con la inmutabilidad financiera del manifiesto.
    """
    bill = _get_bill(db, bill_id, for_update=True)
    if bill.status is SupplierBillStatus.VOID:
        return bill
    if bill.status is not SupplierBillStatus.PENDING or _money(
        bill.balance_due
    ) != _money(bill.total):
        code = bill.code
        db.rollback()
        raise InvalidBillStateError(
            f"La factura '{code}' tiene pagos aplicados o ya está cerrada; "
            "no puede anularse directamente"
        )

    bill.status = SupplierBillStatus.VOID
    bill.balance_due = Decimal("0.00")
    _commit(
        db,
        duplicate_message=f"Conflicto al anular la factura '{bill.code}'",
    )
    db.refresh(bill)
    return bill


def reject_bill_mutation(db: Session, bill_id: int) -> None:
    """Bloquea PATCH/DELETE sobre facturas: route explícito de inmutabilidad."""
    bill = get_supplier_bill(db, bill_id)
    raise ImmutableBillError(
        f"La factura '{bill.code}' es inmutable: registre un abono, anule la "
        "factura (VOID) o emita una nota de contrapartida"
    )


# --------------------------------------------------------------------------- #
# Inmutabilidad financiera (manifiesto, sección 4)
# --------------------------------------------------------------------------- #


@event.listens_for(SupplierBill, "before_update")
def _forbid_bill_field_mutation(mapper, connection, target) -> None:  # noqa: ARG001
    """Solo ``status`` y ``balance_due`` pueden cambiar al registrar abonos."""
    state = inspect(target)
    changed = [
        key
        for key in state.mapper.column_attrs.keys()
        if key not in _BILL_MUTABLE_FIELDS
        and state.attrs[key].history.has_changes()
    ]
    if changed:
        raise ImmutableBillError(
            "Los campos de una factura de proveedor son inmutables: "
            + ", ".join(sorted(changed))
            + "; use abonos, anulación o documentos de contrapartida"
        )


@event.listens_for(SupplierBill, "before_delete")
def _forbid_bill_delete(mapper, connection, target) -> None:  # noqa: ARG001
    raise ImmutableBillError(
        "Las facturas de proveedor no pueden eliminarse: conserve la "
        "trazabilidad financiera"
    )


@event.listens_for(SupplierBillPayment, "before_update")
def _forbid_bill_payment_update(mapper, connection, target) -> None:  # noqa: ARG001
    raise ImmutableBillError(
        "Los abonos registrados no pueden modificarse; registre otro abono"
    )


@event.listens_for(SupplierBillPayment, "before_delete")
def _forbid_bill_payment_delete(mapper, connection, target) -> None:  # noqa: ARG001
    raise ImmutableBillError(
        "Los abonos registrados no pueden eliminarse: conserve el historial"
    )
