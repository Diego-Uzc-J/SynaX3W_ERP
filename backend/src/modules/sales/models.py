"""Modelos de dominio del módulo de Ventas y Facturación.

Implementa las entidades descritas en ``specs/sales_spec.md`` (sección 2):
``Customer``, ``SalesOrder``, ``SalesOrderItem``, ``Invoice`` y ``CreditNote``.

Convenciones alineadas con el resto del ERP:

- claves primarias ``Integer`` y fechas ``Date``/``DateTime(timezone=True)``;
- importes ``Numeric(14, 2)`` con ``CHECK`` de no negatividad;
- enums nativos de PostgreSQL con los valores del contrato;
- ``ON DELETE RESTRICT`` para documentos comerciales inmutables y
  ``CASCADE`` solo en las líneas que dependen de su pedido.

La clase declarativa ``Base`` es transversal y vive en ``src.core.database``.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base
from src.modules.inventory.models import Product


class SalesOrderStatus(str, PyEnum):
    """Estados del ciclo comercial de un pedido o cotización."""

    DRAFT = "DRAFT"
    QUOTATION = "QUOTATION"
    CONFIRMED = "CONFIRMED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class InvoiceStatus(str, PyEnum):
    """Estados fiscales de una factura de venta."""

    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


#: Tipo enum nativo reutilizable con los valores del contrato.
SALES_ORDER_STATUS_TYPE = SAEnum(
    SalesOrderStatus,
    name="sales_order_status",
    native_enum=True,
    validate_strings=True,
)

#: Tipo enum nativo reutilizable con los valores del contrato.
INVOICE_STATUS_TYPE = SAEnum(
    InvoiceStatus,
    name="invoice_status",
    native_enum=True,
    validate_strings=True,
)

#: Importes monetarios del módulo (hasta 999 999 999 999.99).
MONEY = Numeric(14, 2)


class Customer(Base):
    """Persona jurídica o natural que adquiere productos o servicios."""

    __tablename__ = "customers"
    __table_args__ = (
        CheckConstraint(
            "credit_limit >= 0", name="ck_customers_credit_limit_non_negative"
        ),
        Index("ix_customers_company_name", "company_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tax_id: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    contact_name: Mapped[str] = mapped_column(String(150), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    credit_limit: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Documentos comerciales del cliente. La FK RESTRICT impide borrar un
    # cliente con historial; por eso no se declara cascade de borrado.
    orders: Mapped[list[SalesOrder]] = relationship(back_populates="customer")
    invoices: Mapped[list[Invoice]] = relationship(back_populates="customer")

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return f"<Customer id={self.id!r} tax_id={self.tax_id!r}>"


class SalesOrder(Base):
    """Pedido de venta o cotización con sus totales calculados."""

    __tablename__ = "sales_orders"
    __table_args__ = (
        CheckConstraint("subtotal >= 0", name="ck_sales_orders_subtotal_non_negative"),
        CheckConstraint(
            "tax_amount >= 0", name="ck_sales_orders_tax_amount_non_negative"
        ),
        CheckConstraint("total >= 0", name="ck_sales_orders_total_non_negative"),
        Index("ix_sales_orders_customer_id", "customer_id"),
        Index("ix_sales_orders_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(
        String(30), unique=True, nullable=False, index=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[SalesOrderStatus] = mapped_column(
        SALES_ORDER_STATUS_TYPE,
        nullable=False,
        default=SalesOrderStatus.DRAFT,
        server_default=SalesOrderStatus.DRAFT.value,
    )
    issue_date: Mapped[date] = mapped_column(
        Date, nullable=False, default=date.today, server_default=func.current_date()
    )
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    subtotal: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    total: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    customer: Mapped[Customer] = relationship(back_populates="orders")
    # Las líneas dependen del pedido y se eliminan con él mientras siga en
    # borrador; una vez confirmado, la capa de servicio bloquea el borrado.
    items: Mapped[list[SalesOrderItem]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
    )
    invoices: Mapped[list[Invoice]] = relationship(back_populates="sales_order")

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return f"<SalesOrder id={self.id!r} code={self.code!r} status={self.status!r}>"


class SalesOrderItem(Base):
    """Línea de un pedido con precio y tasa de impuesto congelados."""

    __tablename__ = "sales_order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_sales_order_items_quantity_positive"),
        CheckConstraint(
            "unit_price >= 0", name="ck_sales_order_items_unit_price_non_negative"
        ),
        CheckConstraint(
            "tax_rate >= 0 AND tax_rate <= 100",
            name="ck_sales_order_items_tax_rate_range",
        ),
        CheckConstraint(
            "subtotal >= 0", name="ck_sales_order_items_subtotal_non_negative"
        ),
        Index("ix_sales_order_items_sales_order_id", "sales_order_id"),
        Index("ix_sales_order_items_product_id", "product_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sales_order_id: Mapped[int] = mapped_column(
        ForeignKey("sales_orders.id", ondelete="CASCADE"), nullable=False
    )
    # FK lógica al catálogo de inventario; el producto no se puede borrar si
    # aparece en el historial comercial.
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    subtotal: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    order: Mapped[SalesOrder] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return (
            f"<SalesOrderItem id={self.id!r} order_id={self.sales_order_id!r} "
            f"product_id={self.product_id!r} quantity={self.quantity!r}>"
        )


class Invoice(Base):
    """Factura fiscal emitida a partir de un pedido o de forma directa."""

    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint("total >= 0", name="ck_invoices_total_non_negative"),
        CheckConstraint(
            "balance_due >= 0", name="ck_invoices_balance_due_non_negative"
        ),
        Index("ix_invoices_customer_id", "customer_id"),
        Index("ix_invoices_sales_order_id", "sales_order_id"),
        Index("ix_invoices_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(
        String(30), unique=True, nullable=False, index=True
    )
    sales_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("sales_orders.id", ondelete="RESTRICT"), nullable=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[InvoiceStatus] = mapped_column(
        INVOICE_STATUS_TYPE,
        nullable=False,
        default=InvoiceStatus.ISSUED,
        server_default=InvoiceStatus.ISSUED.value,
    )
    issue_date: Mapped[date] = mapped_column(
        Date, nullable=False, default=date.today, server_default=func.current_date()
    )
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    total: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    balance_due: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    sales_order: Mapped[SalesOrder | None] = relationship(back_populates="invoices")
    customer: Mapped[Customer] = relationship(back_populates="invoices")
    credit_notes: Mapped[list[CreditNote]] = relationship(back_populates="invoice")

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return f"<Invoice id={self.id!r} code={self.code!r} status={self.status!r}>"


class CreditNote(Base):
    """Nota crédito por devoluciones o ajustes sobre una factura emitida.

    La regla de inmutabilidad financiera exige anular o acreditar en lugar de
    modificar la factura original; esta entidad materializa esa contrapartida.
    """

    __tablename__ = "credit_notes"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_credit_notes_amount_positive"),
        Index("ix_credit_notes_invoice_id", "invoice_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(
        String(30), unique=True, nullable=False, index=True
    )
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    issue_date: Mapped[date] = mapped_column(
        Date, nullable=False, default=date.today, server_default=func.current_date()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    invoice: Mapped[Invoice] = relationship(back_populates="credit_notes")

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return (
            f"<CreditNote id={self.id!r} code={self.code!r} "
            f"invoice_id={self.invoice_id!r}>"
        )
