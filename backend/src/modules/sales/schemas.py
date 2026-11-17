"""Esquemas Pydantic v2 del módulo de Ventas y Facturación.

Derivados de ``specs/sales_spec.md`` (sección 2) y de los modelos ORM de
``src.modules.sales.models``. Se definen contratos de entrada (``Create``),
actualización parcial (``Update``) y salida (``Response``) para clientes,
pedidos, líneas, facturas y notas crédito.

Principios transversales:

* **Sin asignación masiva**: todos los esquemas declaran
  ``ConfigDict(extra="forbid")``; campos calculados como ``subtotal``,
  ``tax_amount`` o ``total`` se recalculan y nunca se toman del cliente.
* **Dinero estrictamente decimal**: todos los importes usan ``Decimal`` con
  ``max_digits`` y ``decimal_places``; no se aceptan ``float``.
* **Cálculo automático**: ``SalesOrderItemCreate`` calcula su subtotal e
  impuesto, y ``SalesOrderCreate`` agrega ambos a nivel de pedido, conforme a
  la regla de negocio 4.
* **Respuestas desde el ORM**: los esquemas ``Response`` activan
  ``from_attributes=True`` para validar directamente entidades SQLAlchemy.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from src.modules.sales.models import InvoiceStatus, SalesOrderStatus

__all__ = [
    "CreditNoteCreate",
    "CreditNoteResponse",
    "CustomerCreate",
    "CustomerResponse",
    "CustomerUpdate",
    "InvoiceCreate",
    "InvoicePaymentCreate",
    "InvoiceResponse",
    "InvoiceStatus",
    "SalesOrderCreate",
    "SalesOrderItemCreate",
    "SalesOrderItemResponse",
    "SalesOrderResponse",
    "SalesOrderStatus",
    "SalesOrderUpdate",
]

#: Unidad mínima de los importes monetarios del ERP.
_CENT = Decimal("0.01")

#: Límite de ``Numeric(14, 2)`` expresado como Decimal.
_MAX_MONEY = Decimal("999999999999.99")


def _money(value: Decimal) -> Decimal:
    """Redondea a dos decimales y valida el rango de ``Numeric(14, 2)``."""
    rounded = value.quantize(_CENT, rounding=ROUND_HALF_UP)
    if rounded.copy_abs() > _MAX_MONEY:
        raise ValueError("El importe excede el máximo permitido (14,2).")
    return rounded


class SalesSchema(BaseModel):
    """Base de los esquemas de ventas con rechazo de campos desconocidos."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SalesResponseSchema(SalesSchema):
    """Base de las respuestas que se construyen desde entidades SQLAlchemy."""

    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, from_attributes=True
    )


# --------------------------------------------------------------------------- #
# Clientes — /api/v1/sales/customers
# --------------------------------------------------------------------------- #


class CustomerCreate(SalesSchema):
    """Datos requeridos para registrar un cliente."""

    tax_id: str = Field(
        min_length=1,
        max_length=50,
        description="Identificación fiscal única (NIT, RUT, etc.).",
        examples=["900123456-1"],
    )
    company_name: str = Field(
        min_length=1,
        max_length=200,
        description="Razón social o nombre comercial.",
        examples=["Aceros del Norte S.A.S."],
    )
    contact_name: str = Field(
        min_length=1,
        max_length=150,
        description="Persona de contacto para asuntos comerciales.",
        examples=["María Gómez"],
    )
    email: EmailStr = Field(
        max_length=255,
        description="Correo electrónico de facturación.",
        examples=["facturacion@acerosnorte.com"],
    )
    phone: str | None = Field(
        default=None,
        max_length=50,
        description="Teléfono de contacto (opcional).",
    )
    address: str = Field(
        min_length=1,
        max_length=255,
        description="Dirección fiscal o comercial.",
    )
    credit_limit: Decimal = Field(
        default=Decimal("0.00"),
        ge=0,
        max_digits=14,
        decimal_places=2,
        description="Límite máximo de crédito permitido.",
        examples=["5000.00"],
    )
    is_active: bool = Field(
        default=True, description="Indica si el cliente puede operar."
    )


class CustomerUpdate(SalesSchema):
    """Actualización parcial de un cliente (PATCH).

    Se permite limpiar ``phone`` enviando ``null``. El resto de campos, si se
    incluyen, deben tener un valor no nulo.
    """

    tax_id: str | None = Field(default=None, min_length=1, max_length=50)
    company_name: str | None = Field(default=None, min_length=1, max_length=200)
    contact_name: str | None = Field(default=None, min_length=1, max_length=150)
    email: EmailStr | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, min_length=1, max_length=255)
    credit_limit: Decimal | None = Field(
        default=None, ge=0, max_digits=14, decimal_places=2
    )
    is_active: bool | None = None

    @model_validator(mode="after")
    def _validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Debe enviar al menos un campo para actualizar")

        nullable = {"phone"}
        for field in self.model_fields_set - nullable:
            if getattr(self, field) is None:
                raise ValueError(f"El campo '{field}' no puede ser nulo")
        return self


class CustomerResponse(SalesResponseSchema):
    """Representación de salida de un cliente."""

    id: int
    tax_id: str
    company_name: str
    contact_name: str
    email: EmailStr
    phone: str | None
    address: str
    credit_limit: Decimal
    is_active: bool
    created_at: datetime


# --------------------------------------------------------------------------- #
# Pedidos y líneas — /api/v1/sales/orders
# --------------------------------------------------------------------------- #


class SalesOrderItemCreate(SalesSchema):
    """Línea de pedido; el subtotal y el impuesto se calculan aquí.

    ``subtotal`` y ``tax_amount`` se recalculan siempre a partir de
    ``quantity``, ``unit_price`` y ``tax_rate``. Si el cliente los envía, sus
    valores se ignoran, evitando manipulaciones de importes.
    """

    product_id: int = Field(gt=0, description="Producto vendido (inventory).")
    quantity: int = Field(
        gt=0, description="Cantidad solicitada; siempre mayor que cero."
    )
    unit_price: Decimal = Field(
        ge=0,
        max_digits=14,
        decimal_places=2,
        description="Precio unitario acordado en el momento de la venta.",
    )
    tax_rate: Decimal = Field(
        default=Decimal("0.00"),
        ge=0,
        le=100,
        max_digits=5,
        decimal_places=2,
        description="Porcentaje de impuesto aplicado (0–100).",
        examples=["19.00"],
    )
    subtotal: Decimal = Field(
        default=Decimal("0.00"),
        ge=0,
        max_digits=14,
        decimal_places=2,
        description="Calculado como quantity × unit_price.",
    )
    tax_amount: Decimal = Field(
        default=Decimal("0.00"),
        ge=0,
        max_digits=14,
        decimal_places=2,
        description="Calculado como subtotal × tax_rate / 100.",
    )

    @model_validator(mode="after")
    def _calculate_line(self) -> Self:
        subtotal = _money(Decimal(self.quantity) * self.unit_price)
        self.subtotal = subtotal
        self.tax_amount = _money(subtotal * self.tax_rate / Decimal("100"))
        return self


class SalesOrderCreate(SalesSchema):
    """Datos para crear una cotización o un pedido en borrador.

    Si ``code`` se omite, el servicio genera un código secuencial
    ``PED-YYYY-XXXX``; si se envía, debe ser único. Los totales se calculan a
    partir de las líneas y no se aceptan como fuente de verdad: cualquier valor
    enviado en ``subtotal``, ``tax_amount`` o ``total`` se sobrescribe.
    """

    code: str | None = Field(
        default=None,
        min_length=1,
        max_length=30,
        description=(
            "Código único del pedido. Si se omite, el servicio genera uno "
            "secuencial con formato PED-YYYY-XXXX."
        ),
        examples=["PED-2026-0001"],
    )
    customer_id: int = Field(gt=0, description="Cliente que realiza el pedido.")
    status: SalesOrderStatus = Field(
        default=SalesOrderStatus.DRAFT,
        description="Estado inicial del documento.",
    )
    issue_date: date = Field(
        default_factory=date.today,
        description="Fecha de emisión del pedido o cotización.",
    )
    valid_until: date | None = Field(
        default=None,
        description="Fecha de expiración de la cotización (opcional).",
    )
    items: list[SalesOrderItemCreate] = Field(
        min_length=1,
        description="Líneas del pedido; al menos una.",
    )
    subtotal: Decimal = Field(
        default=Decimal("0.00"),
        ge=0,
        max_digits=14,
        decimal_places=2,
        description="Suma de las líneas antes de impuestos (calculado).",
    )
    tax_amount: Decimal = Field(
        default=Decimal("0.00"),
        ge=0,
        max_digits=14,
        decimal_places=2,
        description="Suma de impuestos de las líneas (calculado).",
    )
    total: Decimal = Field(
        default=Decimal("0.00"),
        ge=0,
        max_digits=14,
        decimal_places=2,
        description="subtotal + tax_amount (calculado).",
    )

    @model_validator(mode="after")
    def _calculate_totals(self) -> Self:
        if self.valid_until is not None and self.valid_until < self.issue_date:
            raise ValueError("valid_until no puede ser anterior a issue_date")

        self.subtotal = _money(
            sum((item.subtotal for item in self.items), Decimal("0.00"))
        )
        self.tax_amount = _money(
            sum((item.tax_amount for item in self.items), Decimal("0.00"))
        )
        self.total = _money(self.subtotal + self.tax_amount)
        return self


class SalesOrderUpdate(SalesSchema):
    """Edición parcial de una cotización o pedido aún editable.

    El servicio solo admite cambios mientras el pedido esté en ``DRAFT`` o
    ``QUOTATION``. Si se envían ``items``, reemplazan por completo a las líneas
    anteriores y los totales se recalculan; el ``code`` no se puede modificar.
    """

    customer_id: int | None = Field(
        default=None, gt=0, description="Cliente que realiza el pedido."
    )
    status: SalesOrderStatus | None = Field(
        default=None,
        description="Nuevo estado; solo se admiten DRAFT o QUOTATION.",
    )
    issue_date: date | None = Field(
        default=None, description="Nueva fecha de emisión."
    )
    valid_until: date | None = Field(
        default=None, description="Nueva fecha de expiración (opcional)."
    )
    items: list[SalesOrderItemCreate] | None = Field(
        default=None,
        min_length=1,
        description="Líneas de reemplazo; al menos una si se envían.",
    )

    @model_validator(mode="after")
    def _validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Debe enviar al menos un campo para actualizar")

        nullable = {"valid_until"}
        for field in self.model_fields_set - nullable:
            if getattr(self, field) is None:
                raise ValueError(f"El campo '{field}' no puede ser nulo")
        return self


class SalesOrderItemResponse(SalesResponseSchema):
    """Representación de salida de una línea de pedido."""

    id: int
    sales_order_id: int
    product_id: int
    quantity: int
    unit_price: Decimal
    tax_rate: Decimal
    subtotal: Decimal


class SalesOrderResponse(SalesResponseSchema):
    """Representación de salida de un pedido con sus líneas y totales."""

    id: int
    code: str
    customer_id: int
    status: SalesOrderStatus
    issue_date: date
    valid_until: date | None
    subtotal: Decimal
    tax_amount: Decimal
    total: Decimal
    created_at: datetime
    items: list[SalesOrderItemResponse] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Facturación — /api/v1/sales/invoices
# --------------------------------------------------------------------------- #


class InvoiceCreate(SalesSchema):
    """Datos para emitir una factura desde un pedido o de forma directa.

    Si se indica ``sales_order_id``, el servicio toma el total del pedido
    confirmado. En una factura directa (sin pedido) el total es obligatorio.
    ``balance_due`` no se acepta: al emitir nace igual al total.
    """

    code: str = Field(
        min_length=1,
        max_length=30,
        description="Código único de la factura (por ejemplo, FAC-2026-0001).",
        examples=["FAC-2026-0001"],
    )
    sales_order_id: int | None = Field(
        default=None,
        gt=0,
        description="Pedido de origen (nulo en facturas directas).",
    )
    customer_id: int = Field(gt=0, description="Cliente facturado.")
    issue_date: date = Field(
        default_factory=date.today, description="Fecha de emisión."
    )
    due_date: date = Field(description="Fecha límite de pago.")
    total: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=14,
        decimal_places=2,
        description="Importe total; obligatorio si no hay pedido de origen.",
    )

    @model_validator(mode="after")
    def _validate_invoice(self) -> Self:
        if self.due_date < self.issue_date:
            raise ValueError("due_date no puede ser anterior a issue_date")
        if self.sales_order_id is None and self.total is None:
            raise ValueError(
                "Una factura directa requiere 'total' o un 'sales_order_id'"
            )
        return self


class InvoicePaymentCreate(SalesSchema):
    """Pago total o parcial aplicado a una factura emitida."""

    amount: Decimal = Field(
        gt=0,
        max_digits=14,
        decimal_places=2,
        description="Importe del pago; debe ser mayor que cero.",
        examples=["400.00"],
    )


class InvoiceResponse(SalesResponseSchema):
    """Representación de salida de una factura."""

    id: int
    code: str
    sales_order_id: int | None
    customer_id: int
    status: InvoiceStatus
    issue_date: date
    due_date: date
    total: Decimal
    balance_due: Decimal
    created_at: datetime


# --------------------------------------------------------------------------- #
# Notas crédito — /api/v1/sales/invoices/{id}/credit-notes
# --------------------------------------------------------------------------- #


class CreditNoteCreate(SalesSchema):
    """Nota crédito por devolución o ajuste sobre una factura emitida."""

    code: str = Field(
        min_length=1,
        max_length=30,
        description="Código único de la nota crédito (por ejemplo, NC-2026-0001).",
        examples=["NC-2026-0001"],
    )
    invoice_id: int = Field(gt=0, description="Factura que se acredita.")
    amount: Decimal = Field(
        gt=0,
        max_digits=14,
        decimal_places=2,
        description="Importe acreditado; debe ser mayor que cero.",
        examples=["19.00"],
    )
    reason: str | None = Field(
        default=None,
        description="Motivo de la devolución o ajuste (opcional).",
    )
    issue_date: date = Field(
        default_factory=date.today, description="Fecha de emisión de la nota."
    )


class CreditNoteResponse(SalesResponseSchema):
    """Representación de salida de una nota crédito."""

    id: int
    code: str
    invoice_id: int
    amount: Decimal
    reason: str | None
    issue_date: date
    created_at: datetime
