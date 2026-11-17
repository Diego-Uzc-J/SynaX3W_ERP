"""Servicios de dominio del módulo de Ventas y Facturación.

Implementa la primera capa de reglas de ``specs/sales_spec.md``:

* CRUD de ``Customer`` con unicidad de ``tax_id`` y bloqueo de operaciones
  comerciales para clientes inactivos.
* Alta y edición de ``SalesOrder`` en ``DRAFT``/``QUOTATION``, con generación
  secuencial de códigos ``PED-YYYY-XXXX`` y recálculo automático de subtotales,
  impuestos y total a partir de las líneas.
* Cálculo del saldo pendiente de facturas ``ISSUED`` y validación del límite de
  crédito disponible. La regla 1 de la especificación se aplica al confirmar el
  pedido; se expone ``validate_order_credit`` para que ese hito la invoque sin
  bloquear cotizaciones en borrador.

El módulo es agnóstico de HTTP: las excepciones de dominio declaran su
``status_code`` (400, 404 o 409) y un futuro router las traduce a
``HTTPException``/``JSONResponse`` de FastAPI.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from src.modules.inventory.models import Product
from src.modules.sales.models import (
    Customer,
    Invoice,
    InvoiceStatus,
    SalesOrder,
    SalesOrderItem,
    SalesOrderStatus,
)
from src.modules.sales.schemas import (
    CustomerCreate,
    CustomerUpdate,
    SalesOrderCreate,
    SalesOrderItemCreate,
    SalesOrderUpdate,
)

__all__ = [
    "CreditLimitExceededError",
    "DuplicateResourceError",
    "InactiveCustomerError",
    "InvalidOrderDataError",
    "InvalidOrderStateError",
    "ResourceNotFoundError",
    "SalesServiceError",
    "create_customer",
    "create_sales_order",
    "deactivate_customer",
    "ensure_credit_available",
    "get_available_credit",
    "get_customer",
    "get_pending_balance",
    "get_sales_order",
    "list_customers",
    "list_sales_orders",
    "update_customer",
    "update_sales_order",
    "validate_order_credit",
]

#: Unidad mínima de los importes monetarios del ERP.
_CENT = Decimal("0.01")

#: Límite de ``Numeric(14, 2)`` expresado como Decimal.
_MAX_MONEY = Decimal("999999999999.99")

#: Estados en los que un pedido puede crearse o editarse en este hito.
_EDITABLE_STATUSES = frozenset(
    {SalesOrderStatus.DRAFT, SalesOrderStatus.QUOTATION}
)

#: Clave base del advisory lock que serializa la secuencia de códigos.
_ORDER_CODE_LOCK_BASE = 7_500_000


# --------------------------------------------------------------------------- #
# Excepciones de dominio
# --------------------------------------------------------------------------- #


class SalesServiceError(Exception):
    """Error base del módulo de ventas con su equivalencia HTTP."""

    status_code: int = 400


class ResourceNotFoundError(SalesServiceError):
    """El recurso solicitado no existe."""

    status_code = 404


class DuplicateResourceError(SalesServiceError):
    """Se intentó persistir un valor que debe ser único."""

    status_code = 409


class InactiveCustomerError(SalesServiceError):
    """No se permiten transacciones comerciales con clientes inactivos."""

    status_code = 409


class InvalidOrderStateError(SalesServiceError):
    """La transición o edición no es válida para el estado actual."""

    status_code = 409


class InvalidOrderDataError(SalesServiceError):
    """Los datos del pedido no cumplen una regla de negocio."""

    status_code = 400


class CreditLimitExceededError(SalesServiceError):
    """La deuda del cliente más el nuevo importe supera su límite."""

    status_code = 400

    def __init__(
        self,
        *,
        customer_id: int,
        credit_limit: Decimal,
        pending_balance: Decimal,
        requested: Decimal,
    ) -> None:
        self.customer_id = customer_id
        self.credit_limit = credit_limit
        self.pending_balance = pending_balance
        self.requested = requested
        available = credit_limit - pending_balance
        super().__init__(
            "Límite de crédito excedido para el cliente "
            f"{customer_id}: disponible {available}, solicitado {requested}, "
            f"saldo pendiente {pending_balance}, límite {credit_limit}"
        )


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
    """Verifica que el ``tax_id`` no esté registrado por otro cliente."""
    stmt = select(Customer.id).where(Customer.tax_id == tax_id)
    if exclude_id is not None:
        stmt = stmt.where(Customer.id != exclude_id)
    if db.execute(stmt.limit(1)).first() is not None:
        raise DuplicateResourceError(
            f"Ya existe un cliente con el identificador fiscal '{tax_id}'"
        )


def _ensure_unique_order_code(
    db: Session, code: str, *, exclude_id: int | None = None
) -> None:
    """Verifica que el código de pedido no esté en uso."""
    stmt = select(SalesOrder.id).where(SalesOrder.code == code)
    if exclude_id is not None:
        stmt = stmt.where(SalesOrder.id != exclude_id)
    if db.execute(stmt.limit(1)).first() is not None:
        raise DuplicateResourceError(
            f"Ya existe un pedido con el código '{code}'"
        )


def _get_customer(db: Session, customer_id: int) -> Customer:
    """Obtiene un cliente por id, sin importar su estado."""
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise ResourceNotFoundError(f"Cliente {customer_id} no encontrado")
    return customer


def _get_active_customer(db: Session, customer_id: int) -> Customer:
    """Obtiene un cliente y exige que esté activo para operar."""
    customer = _get_customer(db, customer_id)
    if not customer.is_active:
        raise InactiveCustomerError(
            "No se pueden crear transacciones comerciales para el cliente "
            f"{customer_id} porque está inactivo"
        )
    return customer


def _validate_dates(issue_date: date, valid_until: date | None) -> None:
    """Valida que la vigencia de una cotización no preceda a su emisión."""
    if valid_until is not None and valid_until < issue_date:
        raise InvalidOrderDataError(
            "valid_until no puede ser anterior a issue_date"
        )


def _build_items(
    db: Session, items: Iterable[SalesOrderItemCreate]
) -> list[SalesOrderItem]:
    """Construye las líneas, validando el producto y calculando su subtotal."""
    built: list[SalesOrderItem] = []
    for data in items:
        product = db.get(Product, data.product_id)
        if product is None:
            raise ResourceNotFoundError(
                f"Producto {data.product_id} no encontrado"
            )

        unit_price = _money(data.unit_price)
        tax_rate = _money(data.tax_rate)
        subtotal = _money(Decimal(data.quantity) * unit_price)
        _ensure_money_range(subtotal, label="subtotal de la línea")

        built.append(
            SalesOrderItem(
                product_id=data.product_id,
                quantity=data.quantity,
                unit_price=unit_price,
                tax_rate=tax_rate,
                subtotal=subtotal,
            )
        )

    if not built:
        raise InvalidOrderDataError(
            "El pedido debe incluir al menos una línea"
        )
    return built


def _recalculate_totals(
    items: Iterable[SalesOrderItem],
) -> tuple[Decimal, Decimal, Decimal]:
    """Calcula (subtotal, impuestos, total) suma de las líneas."""
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

    _ensure_money_range(subtotal, label="subtotal del pedido")
    _ensure_money_range(tax_amount, label="importe de impuestos")
    _ensure_money_range(total, label="total del pedido")
    return subtotal, tax_amount, total


def _lock_order_sequence(db: Session, year: int) -> None:
    """Serializa la generación de códigos en PostgreSQL.

    El advisory lock se libera al terminar la transacción. En SQLite (pruebas)
    no aplica y la unicidad queda garantizada por el índice de ``code``.
    """
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        db.execute(
            select(func.pg_advisory_xact_lock(_ORDER_CODE_LOCK_BASE + year))
        )


def _next_order_code(db: Session, year: int) -> str:
    """Devuelve el siguiente código ``PED-YYYY-XXXX`` para el año indicado."""
    prefix = f"PED-{year}-"
    rows = db.scalars(
        select(SalesOrder.code).where(SalesOrder.code.like(f"{prefix}%"))
    ).all()

    max_sequence = 0
    for code in rows:
        suffix = code[len(prefix) :]
        if suffix.isdigit():
            max_sequence = max(max_sequence, int(suffix))
    return f"{prefix}{max_sequence + 1:04d}"


# --------------------------------------------------------------------------- #
# Clientes
# --------------------------------------------------------------------------- #


def create_customer(db: Session, data: CustomerCreate) -> Customer:
    """Registra un cliente validando la unicidad de su ``tax_id``."""
    _ensure_unique_tax_id(db, data.tax_id)
    customer = Customer(**data.model_dump())
    db.add(customer)
    _commit(
        db,
        duplicate_message=(
            "Ya existe un cliente con el identificador fiscal "
            f"'{data.tax_id}'"
        ),
    )
    db.refresh(customer)
    return customer


def get_customer(db: Session, customer_id: int) -> Customer:
    """Obtiene un cliente por id o lanza ``ResourceNotFoundError``."""
    return _get_customer(db, customer_id)


def list_customers(
    db: Session,
    *,
    skip: int = 0,
    limit: int = 100,
    company_name: str | None = None,
    tax_id: str | None = None,
    is_active: bool | None = None,
) -> list[Customer]:
    """Lista clientes con paginación y filtros por razón social o ``tax_id``."""
    stmt = select(Customer)
    if company_name:
        stmt = stmt.where(Customer.company_name.ilike(f"%{company_name}%"))
    if tax_id:
        stmt = stmt.where(Customer.tax_id.ilike(f"%{tax_id}%"))
    if is_active is not None:
        stmt = stmt.where(Customer.is_active.is_(is_active))
    stmt = stmt.order_by(Customer.id).offset(skip).limit(limit)
    return list(db.scalars(stmt).all())


def update_customer(
    db: Session, customer_id: int, data: CustomerUpdate
) -> Customer:
    """Actualiza parcialmente un cliente respetando la unicidad del ``tax_id``.

    Se permite editar clientes inactivos para poder reactivarlos mediante
    ``is_active=True``; las operaciones comerciales siguen bloqueadas mientras
    el cliente permanezca inactivo.
    """
    customer = _get_customer(db, customer_id)
    changes = data.model_dump(exclude_unset=True)

    new_tax_id = changes.get("tax_id")
    if new_tax_id is not None and new_tax_id != customer.tax_id:
        _ensure_unique_tax_id(db, new_tax_id, exclude_id=customer.id)

    for field, value in changes.items():
        setattr(customer, field, value)

    _commit(
        db,
        duplicate_message=(
            "Ya existe un cliente con el identificador fiscal "
            f"'{new_tax_id or customer.tax_id}'"
        ),
    )
    db.refresh(customer)
    return customer


def deactivate_customer(db: Session, customer_id: int) -> Customer:
    """Desactiva un cliente (borrado lógico) preservando su historial.

    No se elimina la fila porque pedidos y facturas la referencian con
    ``ON DELETE RESTRICT``.
    """
    customer = _get_customer(db, customer_id)
    if customer.is_active:
        customer.is_active = False
        db.commit()
        db.refresh(customer)
    return customer


# --------------------------------------------------------------------------- #
# Pedidos y cotizaciones
# --------------------------------------------------------------------------- #


def create_sales_order(db: Session, data: SalesOrderCreate) -> SalesOrder:
    """Crea una cotización o pedido en borrador con totales calculados.

    Si ``data.code`` se omite, se genera un código secuencial
    ``PED-YYYY-XXXX``. Un código explícito duplicado se rechaza con 409.
    Solo se admiten los estados ``DRAFT`` y ``QUOTATION`` en este hito.
    """
    if data.status not in _EDITABLE_STATUSES:
        raise InvalidOrderStateError(
            "Solo se pueden crear pedidos en estado DRAFT o QUOTATION; "
            f"recibido {data.status.value}"
        )

    _get_active_customer(db, data.customer_id)
    _validate_dates(data.issue_date, data.valid_until)
    items = _build_items(db, data.items)
    subtotal, tax_amount, total = _recalculate_totals(items)

    if data.code is None:
        _lock_order_sequence(db, data.issue_date.year)
        code = _next_order_code(db, data.issue_date.year)
    else:
        code = data.code
        _ensure_unique_order_code(db, code)

    order = SalesOrder(
        code=code,
        customer_id=data.customer_id,
        status=data.status,
        issue_date=data.issue_date,
        valid_until=data.valid_until,
        subtotal=subtotal,
        tax_amount=tax_amount,
        total=total,
    )
    order.items = items
    db.add(order)

    _commit(
        db,
        duplicate_message=f"Ya existe un pedido con el código '{code}'",
    )
    db.refresh(order)
    return order


def get_sales_order(db: Session, order_id: int) -> SalesOrder:
    """Obtiene un pedido con sus líneas o lanza ``ResourceNotFoundError``."""
    stmt = (
        select(SalesOrder)
        .where(SalesOrder.id == order_id)
        .options(selectinload(SalesOrder.items))
    )
    order = db.scalars(stmt).first()
    if order is None:
        raise ResourceNotFoundError(f"Pedido {order_id} no encontrado")
    return order


def list_sales_orders(
    db: Session,
    *,
    skip: int = 0,
    limit: int = 100,
    status: SalesOrderStatus | None = None,
    customer_id: int | None = None,
    code: str | None = None,
) -> list[SalesOrder]:
    """Lista pedidos con filtros por estado, cliente o código."""
    stmt = select(SalesOrder).options(selectinload(SalesOrder.items))
    if status is not None:
        stmt = stmt.where(SalesOrder.status == status)
    if customer_id is not None:
        stmt = stmt.where(SalesOrder.customer_id == customer_id)
    if code:
        stmt = stmt.where(SalesOrder.code.ilike(f"%{code}%"))
    stmt = stmt.order_by(SalesOrder.id).offset(skip).limit(limit)
    return list(db.scalars(stmt).all())


def update_sales_order(
    db: Session, order_id: int, data: SalesOrderUpdate
) -> SalesOrder:
    """Edita un pedido mientras permanezca en ``DRAFT`` o ``QUOTATION``.

    Si se envían ``items``, sustituyen a todas las líneas anteriores y los
    totales se recalculan. El ``code`` es inmutable.
    """
    order = get_sales_order(db, order_id)
    if order.status not in _EDITABLE_STATUSES:
        raise InvalidOrderStateError(
            f"El pedido '{order.code}' está en estado {order.status.value} y "
            "solo puede editarse en DRAFT o QUOTATION"
        )

    # Un pedido cuyo cliente fue desactivado tampoco puede seguir editándose.
    _get_active_customer(db, order.customer_id)

    changes = data.model_dump(exclude_unset=True, exclude={"items"})

    new_status = changes.get("status")
    if new_status is not None and new_status not in _EDITABLE_STATUSES:
        raise InvalidOrderStateError(
            "Solo se puede mantener el pedido en DRAFT o QUOTATION; "
            f"recibido {new_status.value}"
        )

    new_customer_id = changes.get("customer_id")
    if new_customer_id is not None and new_customer_id != order.customer_id:
        _get_active_customer(db, new_customer_id)

    issue_date = changes.get("issue_date", order.issue_date)
    valid_until = changes.get("valid_until", order.valid_until)
    _validate_dates(issue_date, valid_until)

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

    for field in ("customer_id", "status", "issue_date", "valid_until"):
        if field in changes:
            setattr(order, field, changes[field])

    _commit(
        db,
        duplicate_message=f"Ya existe un pedido con el código '{order.code}'",
    )
    db.refresh(order)
    return order


# --------------------------------------------------------------------------- #
# Crédito del cliente
# --------------------------------------------------------------------------- #


def get_pending_balance(
    db: Session,
    customer_id: int,
    *,
    exclude_invoice_id: int | None = None,
) -> Decimal:
    """Suma el saldo pendiente de las facturas ``ISSUED`` del cliente."""
    stmt = select(func.coalesce(func.sum(Invoice.balance_due), 0)).where(
        Invoice.customer_id == customer_id,
        Invoice.status == InvoiceStatus.ISSUED,
    )
    if exclude_invoice_id is not None:
        stmt = stmt.where(Invoice.id != exclude_invoice_id)
    return _money(db.scalar(stmt) or 0)


def get_available_credit(db: Session, customer_id: int) -> Decimal:
    """Devuelve ``credit_limit - saldo pendiente`` para un cliente activo."""
    customer = _get_active_customer(db, customer_id)
    pending = get_pending_balance(db, customer_id)
    return _money(_as_decimal(customer.credit_limit) - pending)


def ensure_credit_available(
    db: Session,
    customer_id: int,
    amount: Decimal,
    *,
    exclude_invoice_id: int | None = None,
) -> Decimal:
    """Valida que un nuevo importe quepa en el crédito disponible.

    Considera únicamente el saldo pendiente de facturas ``ISSUED``, tal como
    exige la regla 1 de ``specs/sales_spec.md``. Devuelve el crédito disponible
    tras la operación (``limit - pending - amount``) y lanza
    ``CreditLimitExceededError`` (400) si el importe no cabe.
    """
    requested = _money(amount)
    if requested < 0:
        raise InvalidOrderDataError("El importe a validar no puede ser negativo")

    customer = _get_active_customer(db, customer_id)
    pending = get_pending_balance(
        db, customer_id, exclude_invoice_id=exclude_invoice_id
    )
    credit_limit = _money(customer.credit_limit)
    available = _money(credit_limit - pending)

    if requested > available:
        raise CreditLimitExceededError(
            customer_id=customer_id,
            credit_limit=credit_limit,
            pending_balance=pending,
            requested=requested,
        )
    return _money(available - requested)


def validate_order_credit(db: Session, order: SalesOrder) -> Decimal:
    """Aplica la regla 1 a un pedido que va a confirmarse.

    Se expone como función independiente porque la especificación exige la
    validación de crédito en la transición a ``CONFIRMED``, no al crear
    cotizaciones en borrador. Devuelve el crédito restante tras el pedido.
    """
    return ensure_credit_available(
        db, order.customer_id, _money(order.total)
    )
