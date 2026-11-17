"""Modelos de dominio del módulo de Compras y Proveedores.

Implementa las entidades descritas en ``specs/purchasing_spec.md`` (sección 2):
``Supplier``, ``PurchaseOrder``, ``PurchaseOrderItem``, ``GoodsReceipt``,
``GoodsReceiptItem``, ``SupplierBill`` y ``SupplierBillPayment``.

Convenciones alineadas con ``sales`` e ``inventory``:

- claves primarias ``Integer`` y fechas ``Date``/``DateTime(timezone=True)``;
- importes ``Numeric(14, 2)`` con ``CHECK`` de no negatividad;
- enums nativos de PostgreSQL con los valores del contrato;
- ``ON DELETE RESTRICT`` para documentos comerciales y financieros inmutables;
  ``CASCADE`` solo en las líneas dependientes de su documento.

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
from src.modules.inventory.models import Product, Warehouse


class PurchaseOrderStatus(str, PyEnum):
    """Estados del ciclo de una orden de compra según la spec de purchasing."""

    DRAFT = "DRAFT"
    SENT = "SENT"
    APPROVED = "APPROVED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    COMPLETED = "COMPLETED"
    FORCE_CLOSED = "FORCE_CLOSED"
    CANCELLED = "CANCELLED"


class SupplierBillStatus(str, PyEnum):
    """Estados de una cuenta por pagar de proveedor."""

    PENDING = "PENDING"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOID = "VOID"


#: Tipo enum nativo reutilizable con los valores del contrato.
PURCHASE_ORDER_STATUS_TYPE = SAEnum(
    PurchaseOrderStatus,
    name="purchase_order_status",
    native_enum=True,
    validate_strings=True,
)

#: Tipo enum nativo reutilizable con los valores del contrato.
SUPPLIER_BILL_STATUS_TYPE = SAEnum(
    SupplierBillStatus,
    name="supplier_bill_status",
    native_enum=True,
    validate_strings=True,
)

#: Importes monetarios del módulo (hasta 999 999 999 999.99).
MONEY = Numeric(14, 2)


class Supplier(Base):
    """Tercero que suministra productos o servicios al ERP."""

    __tablename__ = "suppliers"
    __table_args__ = (
        CheckConstraint(
            "payment_terms_days >= 0",
            name="ck_suppliers_payment_terms_days_non_negative",
        ),
        Index("ix_suppliers_company_name", "company_name"),
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
    payment_terms_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default="30"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    orders: Mapped[list[PurchaseOrder]] = relationship(back_populates="supplier")
    bills: Mapped[list[SupplierBill]] = relationship(back_populates="supplier")

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return f"<Supplier id={self.id!r} tax_id={self.tax_id!r}>"


class PurchaseOrder(Base):
    """Orden de compra emitida a un proveedor, con sus totales calculados."""

    __tablename__ = "purchase_orders"
    __table_args__ = (
        CheckConstraint(
            "subtotal >= 0", name="ck_purchase_orders_subtotal_non_negative"
        ),
        CheckConstraint(
            "tax_amount >= 0", name="ck_purchase_orders_tax_amount_non_negative"
        ),
        CheckConstraint("total >= 0", name="ck_purchase_orders_total_non_negative"),
        Index("ix_purchase_orders_supplier_id", "supplier_id"),
        Index("ix_purchase_orders_status", "status"),
        Index("ix_purchase_orders_issue_date", "issue_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(
        String(30), unique=True, nullable=False, index=True
    )
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[PurchaseOrderStatus] = mapped_column(
        PURCHASE_ORDER_STATUS_TYPE,
        nullable=False,
        default=PurchaseOrderStatus.DRAFT,
        server_default=PurchaseOrderStatus.DRAFT.value,
    )
    issue_date: Mapped[date] = mapped_column(
        Date, nullable=False, default=date.today, server_default=func.current_date()
    )
    expected_delivery_date: Mapped[date] = mapped_column(Date, nullable=False)
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

    supplier: Mapped[Supplier] = relationship(back_populates="orders")
    items: Mapped[list[PurchaseOrderItem]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
    )
    receipts: Mapped[list[GoodsReceipt]] = relationship(back_populates="order")
    bills: Mapped[list[SupplierBill]] = relationship(back_populates="purchase_order")

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return (
            f"<PurchaseOrder id={self.id!r} code={self.code!r} status={self.status!r}>"
        )


class PurchaseOrderItem(Base):
    """Línea de una OC con costo, impuesto y cantidades acumuladas."""

    __tablename__ = "purchase_order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_purchase_order_items_quantity_positive"),
        CheckConstraint(
            "received_quantity >= 0 AND received_quantity <= quantity",
            name="ck_purchase_order_items_received_quantity_range",
        ),
        CheckConstraint(
            "unit_price >= 0", name="ck_purchase_order_items_unit_price_non_negative"
        ),
        CheckConstraint(
            "tax_rate >= 0 AND tax_rate <= 100",
            name="ck_purchase_order_items_tax_rate_range",
        ),
        CheckConstraint(
            "subtotal >= 0", name="ck_purchase_order_items_subtotal_non_negative"
        ),
        Index("ix_purchase_order_items_purchase_order_id", "purchase_order_id"),
        Index("ix_purchase_order_items_product_id", "product_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False
    )
    # FK al catálogo de inventario: un producto con historial de compras no se
    # puede eliminar, igual que ocurre en las líneas de venta.
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    received_quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    unit_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    subtotal: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    order: Mapped[PurchaseOrder] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()
    receipt_items: Mapped[list[GoodsReceiptItem]] = relationship(
        back_populates="order_item"
    )

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return (
            f"<PurchaseOrderItem id={self.id!r} order_id={self.purchase_order_id!r} "
            f"product_id={self.product_id!r} quantity={self.quantity!r}>"
        )


class GoodsReceipt(Base):
    """Entrada física de mercancía de una OC en una bodega de inventario."""

    __tablename__ = "goods_receipts"
    __table_args__ = (
        Index("ix_goods_receipts_purchase_order_id", "purchase_order_id"),
        Index("ix_goods_receipts_warehouse_id", "warehouse_id"),
        Index("ix_goods_receipts_receipt_date", "receipt_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(
        String(30), unique=True, nullable=False, index=True
    )
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="RESTRICT"), nullable=False
    )
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    receipt_date: Mapped[date] = mapped_column(
        Date, nullable=False, default=date.today, server_default=func.current_date()
    )
    # La spec admite texto o identificador de usuario; se guarda como texto
    # para no acoplar el documento a la tabla de usuarios.
    received_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    order: Mapped[PurchaseOrder] = relationship(back_populates="receipts")
    warehouse: Mapped[Warehouse] = relationship()
    items: Mapped[list[GoodsReceiptItem]] = relationship(
        back_populates="receipt",
        cascade="all, delete-orphan",
    )
    bills: Mapped[list[SupplierBill]] = relationship(back_populates="goods_receipt")

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return f"<GoodsReceipt id={self.id!r} code={self.code!r}>"


class GoodsReceiptItem(Base):
    """Cantidad física recibida de una línea concreta de la OC."""

    __tablename__ = "goods_receipt_items"
    __table_args__ = (
        CheckConstraint(
            "quantity > 0", name="ck_goods_receipt_items_quantity_positive"
        ),
        Index(
            "ix_goods_receipt_items_goods_receipt_id",
            "goods_receipt_id",
        ),
        Index(
            "ix_goods_receipt_items_purchase_order_item_id",
            "purchase_order_item_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    goods_receipt_id: Mapped[int] = mapped_column(
        ForeignKey("goods_receipts.id", ondelete="CASCADE"), nullable=False
    )
    # La línea de OC es historial inmutable: la recepción la referencia, pero
    # no puede borrarla.
    purchase_order_item_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_order_items.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    receipt: Mapped[GoodsReceipt] = relationship(back_populates="items")
    order_item: Mapped[PurchaseOrderItem] = relationship(back_populates="receipt_items")

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return (
            f"<GoodsReceiptItem id={self.id!r} receipt_id={self.goods_receipt_id!r} "
            f"order_item_id={self.purchase_order_item_id!r} quantity={self.quantity!r}>"
        )


class SupplierBill(Base):
    """Cuenta por pagar derivada de una OC o de una recepción de mercancía."""

    __tablename__ = "supplier_bills"
    __table_args__ = (
        CheckConstraint(
            "subtotal >= 0", name="ck_supplier_bills_subtotal_non_negative"
        ),
        CheckConstraint(
            "tax_amount >= 0", name="ck_supplier_bills_tax_amount_non_negative"
        ),
        CheckConstraint("total >= 0", name="ck_supplier_bills_total_non_negative"),
        CheckConstraint(
            "balance_due >= 0", name="ck_supplier_bills_balance_due_non_negative"
        ),
        CheckConstraint(
            "balance_due <= total", name="ck_supplier_bills_balance_due_not_over_total"
        ),
        CheckConstraint(
            "purchase_order_id IS NOT NULL OR goods_receipt_id IS NOT NULL",
            name="ck_supplier_bills_has_source_document",
        ),
        Index("ix_supplier_bills_supplier_id", "supplier_id"),
        Index("ix_supplier_bills_purchase_order_id", "purchase_order_id"),
        Index("ix_supplier_bills_goods_receipt_id", "goods_receipt_id"),
        Index("ix_supplier_bills_status", "status"),
        Index("ix_supplier_bills_due_date", "due_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(
        String(30), unique=True, nullable=False, index=True
    )
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False
    )
    purchase_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="RESTRICT"), nullable=True
    )
    goods_receipt_id: Mapped[int | None] = mapped_column(
        ForeignKey("goods_receipts.id", ondelete="RESTRICT"), nullable=True
    )
    supplier_invoice_number: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[SupplierBillStatus] = mapped_column(
        SUPPLIER_BILL_STATUS_TYPE,
        nullable=False,
        default=SupplierBillStatus.PENDING,
        server_default=SupplierBillStatus.PENDING.value,
    )
    issue_date: Mapped[date] = mapped_column(
        Date, nullable=False, default=date.today, server_default=func.current_date()
    )
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    total: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    balance_due: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    supplier: Mapped[Supplier] = relationship(back_populates="bills")
    purchase_order: Mapped[PurchaseOrder | None] = relationship(
        back_populates="bills"
    )
    goods_receipt: Mapped[GoodsReceipt | None] = relationship(back_populates="bills")
    payments: Mapped[list[SupplierBillPayment]] = relationship(
        back_populates="bill",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return (
            f"<SupplierBill id={self.id!r} code={self.code!r} status={self.status!r}>"
        )


class SupplierBillPayment(Base):
    """Abono aplicado a una cuenta por pagar.

    Como ``InvoicePayment`` en ``sales``, materializa el historial que respalda
    ``SupplierBill.balance_due``. Es un documento inmutable: las correcciones se
    hacen con nuevos abonos o con la anulación de la factura, nunca editando el
    abono original. ``ON DELETE RESTRICT`` preserva la trazabilidad financiera.
    """

    __tablename__ = "supplier_bill_payments"
    __table_args__ = (
        CheckConstraint(
            "amount > 0", name="ck_supplier_bill_payments_amount_positive"
        ),
        Index("ix_supplier_bill_payments_bill_id", "bill_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bill_id: Mapped[int] = mapped_column(
        ForeignKey("supplier_bills.id", ondelete="RESTRICT"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    paid_at: Mapped[date] = mapped_column(
        Date, nullable=False, default=date.today, server_default=func.current_date()
    )
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    bill: Mapped[SupplierBill] = relationship(back_populates="payments")

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return (
            f"<SupplierBillPayment id={self.id!r} bill_id={self.bill_id!r} "
            f"amount={self.amount!r}>"
        )


__all__ = [
    "MONEY",
    "GoodsReceipt",
    "GoodsReceiptItem",
    "PurchaseOrder",
    "PurchaseOrderItem",
    "PurchaseOrderStatus",
    "Supplier",
    "SupplierBill",
    "SupplierBillPayment",
    "SupplierBillStatus",
]
