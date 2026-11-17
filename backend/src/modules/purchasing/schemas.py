"""Esquemas Pydantic v2 del módulo de Compras y Proveedores.

Derivados de ``specs/purchasing_spec.md`` (sección 2) y de los modelos ORM de
``src.modules.purchasing.models``. Define contratos de entrada (``Create``),
actualización parcial (``Update``) y salida (``Response``) para proveedores,
órdenes de compra, recepciones y cuentas por pagar.

Principios transversales:

* **Sin asignación masiva**: todos los esquemas declaran
  ``ConfigDict(extra="forbid")``; los campos calculados (``subtotal``,
  ``tax_amount``, ``total``, ``balance_due``) se recalculan y nunca se toman
  como fuente de verdad del cliente.
* **Dinero estrictamente decimal**: todos los importes usan ``Decimal`` con
  ``max_digits=14`` y ``decimal_places=2``, alineados con ``Numeric(14, 2)``;
  se recomienda enviarlos como cadenas de dos decimales.
* **Cálculo automático**: ``PurchaseOrderItemCreate`` deriva su subtotal y
  impuesto, y ``PurchaseOrderCreate`` agrega ambos a nivel de pedido.
* **Validaciones de documento**: el CHECK de origen de ``SupplierBill`` y la
  unicidad de líneas en una recepción se reflejan ya en la capa de esquemas;
  las reglas que requieren estado en base de datos (proveedor/producto activo,
  sobre-recepción, consistencia con la OC) permanecen en la capa de servicio.
* **Respuestas desde el ORM**: los esquemas ``Response`` activan
  ``from_attributes=True`` para validar directamente entidades SQLAlchemy.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from src.modules.purchasing.models import PurchaseOrderStatus, SupplierBillStatus

__all__ = [
    "GoodsReceiptCreate",
    "GoodsReceiptItemCreate",
    "GoodsReceiptItemResponse",
    "GoodsReceiptResponse",
    "PurchaseOrderCreate",
    "PurchaseOrderItemCreate",
    "PurchaseOrderItemResponse",
    "PurchaseOrderResponse",
    "PurchaseOrderStatus",
    "PurchaseOrderUpdate",
    "SupplierBillCreate",
    "SupplierBillResponse",
    "SupplierBillStatus",
    "SupplierCreate",
    "SupplierResponse",
    "SupplierUpdate",
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


class PurchasingSchema(BaseModel):
    """Base de los esquemas de compras con rechazo de campos desconocidos."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PurchasingResponseSchema(PurchasingSchema):
    """Base de las respuestas que se construyen desde entidades SQLAlchemy."""

    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, from_attributes=True
    )


# --------------------------------------------------------------------------- #
# Proveedores — /api/v1/purchasing/suppliers
# --------------------------------------------------------------------------- #


class SupplierCreate(PurchasingSchema):
    """Datos requeridos para registrar un proveedor."""

    tax_id: str = Field(
        min_length=1,
        max_length=50,
        description="Identificación tributaria única (NIT, RUT, etc.).",
        examples=["800987654-3"],
    )
    company_name: str = Field(
        min_length=1,
        max_length=200,
        description="Razón social del proveedor.",
        examples=["Aceros del Norte S.A.S."],
    )
    contact_name: str = Field(
        min_length=1,
        max_length=150,
        description="Persona de contacto del proveedor.",
        examples=["María Gómez"],
    )
    email: EmailStr = Field(
        max_length=255,
        description="Correo para el envío de órdenes de compra.",
        examples=["ventas@acerosnorte.com"],
    )
    phone: str | None = Field(
        default=None,
        max_length=50,
        description="Teléfono de contacto (opcional).",
    )
    address: str = Field(
        min_length=1,
        max_length=255,
        description="Dirección del proveedor.",
    )
    payment_terms_days: int = Field(
        default=30,
        ge=0,
        description="Plazo de pago acordado en días; no puede ser negativo.",
        examples=[30, 60],
    )
    is_active: bool = Field(
        default=True,
        description="Indica si el proveedor puede recibir órdenes de compra.",
    )


class SupplierUpdate(PurchasingSchema):
    """Actualización parcial de un proveedor (PATCH).

    Se permite limpiar ``phone`` enviando ``null``. El resto de campos, si se
    incluyen, deben tener un valor no nulo.
    """

    tax_id: str | None = Field(default=None, min_length=1, max_length=50)
    company_name: str | None = Field(default=None, min_length=1, max_length=200)
    contact_name: str | None = Field(default=None, min_length=1, max_length=150)
    email: EmailStr | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, min_length=1, max_length=255)
    payment_terms_days: int | None = Field(default=None, ge=0)
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


class SupplierResponse(PurchasingResponseSchema):
    """Representación de salida de un proveedor."""

    id: int
    tax_id: str
    company_name: str
    contact_name: str
    email: EmailStr
    phone: str | None
    address: str
    payment_terms_days: int
    is_active: bool
    created_at: datetime


# --------------------------------------------------------------------------- #
# Órdenes de compra — /api/v1/purchasing/orders
# --------------------------------------------------------------------------- #


class PurchaseOrderItemCreate(PurchasingSchema):
    """Línea de OC; el subtotal y el impuesto se calculan aquí.

    ``subtotal`` y ``tax_amount`` se recalculan siempre desde ``quantity``,
    ``unit_price`` y ``tax_rate``. El impuesto es un dato derivado usado para
    agregar el total de la orden; el modelo ORM no lo persiste en la línea.
    """

    product_id: int = Field(gt=0, description="Producto a comprar (inventory).")
    quantity: int = Field(gt=0, description="Cantidad ordenada; siempre > 0.")
    unit_price: Decimal = Field(
        ge=0,
        max_digits=14,
        decimal_places=2,
        description="Costo unitario pactado con el proveedor.",
        examples=["1250.00"],
    )
    tax_rate: Decimal = Field(
        default=Decimal("0.00"),
        ge=0,
        le=100,
        max_digits=5,
        decimal_places=2,
        description="Porcentaje de impuesto aplicable (0–100).",
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
        description="Calculado como subtotal × tax_rate / 100 (no persistido).",
    )

    @model_validator(mode="after")
    def _calculate_line(self) -> Self:
        subtotal = _money(Decimal(self.quantity) * self.unit_price)
        self.subtotal = subtotal
        self.tax_amount = _money(subtotal * self.tax_rate / Decimal("100"))
        return self


class PurchaseOrderCreate(PurchasingSchema):
    """Datos para crear una orden de compra en borrador (``DRAFT``).

    Si ``code`` se omite, el servicio genera un código secuencial
    ``OC-YYYY-XXXX``. Los totales se calculan a partir de las líneas: cualquier
    valor enviado en ``subtotal``, ``tax_amount`` o ``total`` se sobrescribe.
    El estado inicial lo fija el servicio en ``DRAFT`` conforme a la spec.
    """

    code: str | None = Field(
        default=None,
        min_length=1,
        max_length=30,
        description=(
            "Código único de la OC. Si se omite, el servicio genera uno "
            "secuencial con formato OC-YYYY-XXXX."
        ),
        examples=["OC-2026-0001"],
    )
    supplier_id: int = Field(gt=0, description="Proveedor al que se emite la OC.")
    issue_date: date = Field(
        default_factory=date.today, description="Fecha de emisión de la OC."
    )
    expected_delivery_date: date = Field(description="Fecha estimada de entrega.")
    items: list[PurchaseOrderItemCreate] = Field(
        min_length=1,
        description="Líneas de la OC; al menos una.",
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
        if self.expected_delivery_date < self.issue_date:
            raise ValueError("expected_delivery_date no puede ser anterior a issue_date")

        self.subtotal = _money(
            sum((item.subtotal for item in self.items), Decimal("0.00"))
        )
        self.tax_amount = _money(
            sum((item.tax_amount for item in self.items), Decimal("0.00"))
        )
        self.total = _money(self.subtotal + self.tax_amount)
        return self


class PurchaseOrderUpdate(PurchasingSchema):
    """Edición parcial de una OC aún editable.

    El servicio solo admite cambios mientras la orden esté en ``DRAFT`` o
    ``SENT`` (regla de negocio 1: una vez `APPROVED` sus líneas son
    inmutables). Si se envían ``items``, reemplazan por completo a las líneas
    anteriores y el servicio recalcula los totales. El ``code`` no se puede
    modificar.
    """

    supplier_id: int | None = Field(default=None, gt=0)
    issue_date: date | None = Field(default=None)
    expected_delivery_date: date | None = Field(default=None)
    items: list[PurchaseOrderItemCreate] | None = Field(
        default=None,
        min_length=1,
        description="Líneas de reemplazo; al menos una si se envían.",
    )

    @model_validator(mode="after")
    def _validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Debe enviar al menos un campo para actualizar")

        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"El campo '{field}' no puede ser nulo")

        issue_date = self.issue_date
        expected = self.expected_delivery_date
        if expected is not None and issue_date is not None and expected < issue_date:
            raise ValueError("expected_delivery_date no puede ser anterior a issue_date")
        return self


class PurchaseOrderItemResponse(PurchasingResponseSchema):
    """Representación de salida de una línea de orden de compra."""

    id: int
    purchase_order_id: int
    product_id: int
    quantity: int
    received_quantity: int
    unit_price: Decimal
    tax_rate: Decimal
    subtotal: Decimal


class PurchaseOrderResponse(PurchasingResponseSchema):
    """Representación de salida de una OC con sus líneas y totales."""

    id: int
    code: str
    supplier_id: int
    status: PurchaseOrderStatus
    issue_date: date
    expected_delivery_date: date
    subtotal: Decimal
    tax_amount: Decimal
    total: Decimal
    created_at: datetime
    items: list[PurchaseOrderItemResponse] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Recepción de mercancía — /api/v1/purchasing/receipts
# --------------------------------------------------------------------------- #


class GoodsReceiptItemCreate(PurchasingSchema):
    """Cantidad física recibida de una línea concreta de la OC."""

    purchase_order_item_id: int = Field(
        gt=0, description="Línea de la OC que se está recibiendo."
    )
    quantity: int = Field(gt=0, description="Cantidad recibida; siempre > 0.")


class GoodsReceiptCreate(PurchasingSchema):
    """Datos para registrar una recepción de mercancía.

    Si ``code`` se omite, el servicio genera un código ``REC-YYYY-XXXX``.
    El servicio valida contra la base de datos que la OC esté aprobada, que no
    se supere la cantidad pendiente de cada línea (regla de negocio 4) y
    actualiza el stock con un movimiento ``INBOUND`` (regla 2).
    """

    code: str | None = Field(
        default=None,
        min_length=1,
        max_length=30,
        description=(
            "Código único de la recepción. Si se omite, se genera uno "
            "secuencial con formato REC-YYYY-XXXX."
        ),
        examples=["REC-2026-0001"],
    )
    purchase_order_id: int = Field(gt=0, description="OC que se recibe.")
    warehouse_id: int = Field(gt=0, description="Bodega destino (inventory).")
    receipt_date: date = Field(
        default_factory=date.today, description="Fecha física de recepción."
    )
    received_by: str | None = Field(
        default=None,
        max_length=100,
        description="Persona o usuario que recibe la mercancía.",
    )
    notes: str | None = Field(default=None, description="Observaciones (opcional).")
    items: list[GoodsReceiptItemCreate] = Field(
        min_length=1,
        description="Líneas recibidas; al menos una.",
    )

    @model_validator(mode="after")
    def _validate_items(self) -> Self:
        seen: set[int] = set()
        for item in self.items:
            if item.purchase_order_item_id in seen:
                raise ValueError(
                    "No se puede recibir dos veces la misma línea de orden "
                    "en una sola recepción"
                )
            seen.add(item.purchase_order_item_id)
        return self


class GoodsReceiptItemResponse(PurchasingResponseSchema):
    """Representación de salida de una línea de recepción."""

    id: int
    goods_receipt_id: int
    purchase_order_item_id: int
    quantity: int


class GoodsReceiptResponse(PurchasingResponseSchema):
    """Representación de salida de una recepción con sus líneas."""

    id: int
    code: str
    purchase_order_id: int
    warehouse_id: int
    receipt_date: date
    received_by: str | None
    notes: str | None
    created_at: datetime
    items: list[GoodsReceiptItemResponse] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Cuentas por pagar — /api/v1/purchasing
# --------------------------------------------------------------------------- #


class SupplierBillCreate(PurchasingSchema):
    """Datos para registrar la factura de un proveedor.

    Debe indicarse ``purchase_order_id``, ``goods_receipt_id`` o ambos, tal
    como exige el CHECK ``ck_supplier_bills_has_source_document``. Si se omite
    ``due_date``, el servicio la calcula como
    ``issue_date + supplier.payment_terms_days`` (spec, sección 2.5).
    ``total`` y ``balance_due`` se derivan de ``subtotal`` + ``tax_amount``;
    la factura nace en estado ``PENDING`` con el saldo igual al total. La
    consistencia con costos pactados y cantidades recibidas (regla 6) se valida
    en el servicio contra la OC y la recepción.
    """

    code: str | None = Field(
        default=None,
        min_length=1,
        max_length=30,
        description=(
            "Código único de la cuenta por pagar. Si se omite, se genera "
            "uno secuencial con formato BILL-YYYY-XXXX."
        ),
        examples=["BILL-2026-0001"],
    )
    supplier_id: int = Field(gt=0, description="Proveedor facturador.")
    purchase_order_id: int | None = Field(
        default=None, gt=0, description="OC de origen (opcional)."
    )
    goods_receipt_id: int | None = Field(
        default=None, gt=0, description="Recepción de origen (opcional)."
    )
    supplier_invoice_number: str = Field(
        min_length=1,
        max_length=100,
        description="Número de la factura física emitida por el proveedor.",
        examples=["F-2026-0042"],
    )
    issue_date: date = Field(
        default_factory=date.today, description="Fecha de emisión de la factura."
    )
    due_date: date | None = Field(
        default=None,
        description=(
            "Fecha límite de pago. Si se omite, se deriva de los plazos del proveedor."
        ),
    )
    subtotal: Decimal = Field(
        ge=0,
        max_digits=14,
        decimal_places=2,
        description="Base imponible de la factura.",
        examples=["2500.00"],
    )
    tax_amount: Decimal = Field(
        default=Decimal("0.00"),
        ge=0,
        max_digits=14,
        decimal_places=2,
        description="Impuestos de la factura.",
        examples=["475.00"],
    )
    total: Decimal = Field(
        default=Decimal("0.00"),
        ge=0,
        max_digits=14,
        decimal_places=2,
        description="subtotal + tax_amount (calculado).",
    )
    balance_due: Decimal = Field(
        default=Decimal("0.00"),
        ge=0,
        max_digits=14,
        decimal_places=2,
        description="Saldo pendiente; nace igual al total (calculado).",
    )

    @model_validator(mode="after")
    def _validate_bill(self) -> Self:
        if self.purchase_order_id is None and self.goods_receipt_id is None:
            raise ValueError(
                "La factura debe vincularse a una orden de compra o a una recepción"
            )
        if self.due_date is not None and self.due_date < self.issue_date:
            raise ValueError("due_date no puede ser anterior a issue_date")

        self.total = _money(self.subtotal + self.tax_amount)
        self.balance_due = self.total
        return self


class SupplierBillResponse(PurchasingResponseSchema):
    """Representación de salida de una cuenta por pagar."""

    id: int
    code: str
    supplier_id: int
    purchase_order_id: int | None
    goods_receipt_id: int | None
    supplier_invoice_number: str
    status: SupplierBillStatus
    issue_date: date
    due_date: date
    subtotal: Decimal
    tax_amount: Decimal
    total: Decimal
    balance_due: Decimal
    created_at: datetime
