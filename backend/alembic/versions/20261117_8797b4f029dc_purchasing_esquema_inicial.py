"""purchasing: esquema inicial

Revision ID: 8797b4f029dc
Revises: 20261117_0002
Create Date: 2026-11-17 18:12:42.132201+00:00

Crea el esquema del módulo de Compras y Proveedores conforme a
``specs/purchasing_spec.md`` (sección 2) y a
``backend/src/modules/purchasing/models.py``:

- enums nativos ``purchase_order_status`` y ``supplier_bill_status``
- ``suppliers`` y ``purchase_orders`` / ``purchase_order_items``
- ``goods_receipts`` y ``goods_receipt_items`` (integración con ``inventory``)
- ``supplier_bills`` (cuentas por pagar vinculadas a OC o recepción)

Los tipos enum se crean y eliminan explícitamente, igual que en la migración
inicial de ``sales``, para que el ciclo ``upgrade`` / ``downgrade`` sea
repetible en PostgreSQL.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8797b4f029dc"
down_revision: str | None = "20261117_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PURCHASE_ORDER_STATUS_VALUES = (
    "DRAFT",
    "SENT",
    "APPROVED",
    "PARTIALLY_RECEIVED",
    "COMPLETED",
    "FORCE_CLOSED",
    "CANCELLED",
)

SUPPLIER_BILL_STATUS_VALUES = (
    "PENDING",
    "PARTIALLY_PAID",
    "PAID",
    "VOID",
)


def _purchase_order_status_enum() -> postgresql.ENUM:
    """Tipo enum reutilizable que no intenta crear el tipo por segunda vez."""
    return postgresql.ENUM(
        *PURCHASE_ORDER_STATUS_VALUES,
        name="purchase_order_status",
        create_type=False,
    )


def _supplier_bill_status_enum() -> postgresql.ENUM:
    """Tipo enum reutilizable que no intenta crear el tipo por segunda vez."""
    return postgresql.ENUM(
        *SUPPLIER_BILL_STATUS_VALUES,
        name="supplier_bill_status",
        create_type=False,
    )


def upgrade() -> None:
    bind = op.get_bind()

    # Los enums nativos deben existir antes de las tablas que los usan.
    postgresql.ENUM(
        *PURCHASE_ORDER_STATUS_VALUES, name="purchase_order_status"
    ).create(bind, checkfirst=True)
    postgresql.ENUM(
        *SUPPLIER_BILL_STATUS_VALUES, name="supplier_bill_status"
    ).create(bind, checkfirst=True)

    op.create_table(
        "suppliers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tax_id", sa.String(length=50), nullable=False),
        sa.Column("company_name", sa.String(length=200), nullable=False),
        sa.Column("contact_name", sa.String(length=150), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("address", sa.String(length=255), nullable=False),
        sa.Column(
            "payment_terms_days",
            sa.Integer(),
            server_default="30",
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "payment_terms_days >= 0",
            name="ck_suppliers_payment_terms_days_non_negative",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_suppliers_company_name", "suppliers", ["company_name"], unique=False)
    op.create_index(op.f("ix_suppliers_tax_id"), "suppliers", ["tax_id"], unique=True)

    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            _purchase_order_status_enum(),
            server_default=sa.text("'DRAFT'"),
            nullable=False,
        ),
        sa.Column(
            "issue_date",
            sa.Date(),
            server_default=sa.text("CURRENT_DATE"),
            nullable=False,
        ),
        sa.Column("expected_delivery_date", sa.Date(), nullable=False),
        sa.Column(
            "subtotal",
            sa.Numeric(precision=14, scale=2),
            server_default=sa.text("0.00"),
            nullable=False,
        ),
        sa.Column(
            "tax_amount",
            sa.Numeric(precision=14, scale=2),
            server_default=sa.text("0.00"),
            nullable=False,
        ),
        sa.Column(
            "total",
            sa.Numeric(precision=14, scale=2),
            server_default=sa.text("0.00"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "subtotal >= 0", name="ck_purchase_orders_subtotal_non_negative"
        ),
        sa.CheckConstraint(
            "tax_amount >= 0", name="ck_purchase_orders_tax_amount_non_negative"
        ),
        sa.CheckConstraint("total >= 0", name="ck_purchase_orders_total_non_negative"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_purchase_orders_code"), "purchase_orders", ["code"], unique=True)
    op.create_index("ix_purchase_orders_issue_date", "purchase_orders", ["issue_date"], unique=False)
    op.create_index("ix_purchase_orders_status", "purchase_orders", ["status"], unique=False)
    op.create_index("ix_purchase_orders_supplier_id", "purchase_orders", ["supplier_id"], unique=False)

    op.create_table(
        "purchase_order_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("received_quantity", sa.Integer(), server_default="0", nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "tax_rate",
            sa.Numeric(precision=5, scale=2),
            server_default=sa.text("0.00"),
            nullable=False,
        ),
        sa.Column("subtotal", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.CheckConstraint(
            "quantity > 0", name="ck_purchase_order_items_quantity_positive"
        ),
        sa.CheckConstraint(
            "received_quantity >= 0 AND received_quantity <= quantity",
            name="ck_purchase_order_items_received_quantity_range",
        ),
        sa.CheckConstraint(
            "unit_price >= 0", name="ck_purchase_order_items_unit_price_non_negative"
        ),
        sa.CheckConstraint(
            "tax_rate >= 0 AND tax_rate <= 100",
            name="ck_purchase_order_items_tax_rate_range",
        ),
        sa.CheckConstraint(
            "subtotal >= 0", name="ck_purchase_order_items_subtotal_non_negative"
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["purchase_order_id"], ["purchase_orders.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_purchase_order_items_product_id", "purchase_order_items", ["product_id"], unique=False)
    op.create_index("ix_purchase_order_items_purchase_order_id", "purchase_order_items", ["purchase_order_id"], unique=False)

    op.create_table(
        "goods_receipts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=False),
        sa.Column(
            "receipt_date",
            sa.Date(),
            server_default=sa.text("CURRENT_DATE"),
            nullable=False,
        ),
        sa.Column("received_by", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["purchase_order_id"], ["purchase_orders.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_goods_receipts_code"), "goods_receipts", ["code"], unique=True)
    op.create_index("ix_goods_receipts_purchase_order_id", "goods_receipts", ["purchase_order_id"], unique=False)
    op.create_index("ix_goods_receipts_receipt_date", "goods_receipts", ["receipt_date"], unique=False)
    op.create_index("ix_goods_receipts_warehouse_id", "goods_receipts", ["warehouse_id"], unique=False)

    op.create_table(
        "goods_receipt_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("goods_receipt_id", sa.Integer(), nullable=False),
        sa.Column("purchase_order_item_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "quantity > 0", name="ck_goods_receipt_items_quantity_positive"
        ),
        sa.ForeignKeyConstraint(
            ["goods_receipt_id"], ["goods_receipts.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["purchase_order_item_id"],
            ["purchase_order_items.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_goods_receipt_items_goods_receipt_id", "goods_receipt_items", ["goods_receipt_id"], unique=False)
    op.create_index("ix_goods_receipt_items_purchase_order_item_id", "goods_receipt_items", ["purchase_order_item_id"], unique=False)

    op.create_table(
        "supplier_bills",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), nullable=True),
        sa.Column("goods_receipt_id", sa.Integer(), nullable=True),
        sa.Column("supplier_invoice_number", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            _supplier_bill_status_enum(),
            server_default=sa.text("'PENDING'"),
            nullable=False,
        ),
        sa.Column(
            "issue_date",
            sa.Date(),
            server_default=sa.text("CURRENT_DATE"),
            nullable=False,
        ),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column(
            "subtotal",
            sa.Numeric(precision=14, scale=2),
            server_default=sa.text("0.00"),
            nullable=False,
        ),
        sa.Column(
            "tax_amount",
            sa.Numeric(precision=14, scale=2),
            server_default=sa.text("0.00"),
            nullable=False,
        ),
        sa.Column(
            "total",
            sa.Numeric(precision=14, scale=2),
            server_default=sa.text("0.00"),
            nullable=False,
        ),
        sa.Column(
            "balance_due",
            sa.Numeric(precision=14, scale=2),
            server_default=sa.text("0.00"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "subtotal >= 0", name="ck_supplier_bills_subtotal_non_negative"
        ),
        sa.CheckConstraint(
            "tax_amount >= 0", name="ck_supplier_bills_tax_amount_non_negative"
        ),
        sa.CheckConstraint("total >= 0", name="ck_supplier_bills_total_non_negative"),
        sa.CheckConstraint(
            "balance_due >= 0", name="ck_supplier_bills_balance_due_non_negative"
        ),
        sa.CheckConstraint(
            "balance_due <= total", name="ck_supplier_bills_balance_due_not_over_total"
        ),
        sa.CheckConstraint(
            "purchase_order_id IS NOT NULL OR goods_receipt_id IS NOT NULL",
            name="ck_supplier_bills_has_source_document",
        ),
        sa.ForeignKeyConstraint(
            ["goods_receipt_id"], ["goods_receipts.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["purchase_order_id"], ["purchase_orders.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_supplier_bills_code"), "supplier_bills", ["code"], unique=True)
    op.create_index("ix_supplier_bills_due_date", "supplier_bills", ["due_date"], unique=False)
    op.create_index("ix_supplier_bills_goods_receipt_id", "supplier_bills", ["goods_receipt_id"], unique=False)
    op.create_index("ix_supplier_bills_purchase_order_id", "supplier_bills", ["purchase_order_id"], unique=False)
    op.create_index("ix_supplier_bills_status", "supplier_bills", ["status"], unique=False)
    op.create_index("ix_supplier_bills_supplier_id", "supplier_bills", ["supplier_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()

    # Orden inverso: cuentas por pagar, líneas de recepción, recepciones,
    # líneas de OC, órdenes y proveedores.
    op.drop_index("ix_supplier_bills_supplier_id", table_name="supplier_bills")
    op.drop_index("ix_supplier_bills_status", table_name="supplier_bills")
    op.drop_index("ix_supplier_bills_purchase_order_id", table_name="supplier_bills")
    op.drop_index("ix_supplier_bills_goods_receipt_id", table_name="supplier_bills")
    op.drop_index("ix_supplier_bills_due_date", table_name="supplier_bills")
    op.drop_index(op.f("ix_supplier_bills_code"), table_name="supplier_bills")
    op.drop_table("supplier_bills")

    op.drop_index("ix_goods_receipt_items_purchase_order_item_id", table_name="goods_receipt_items")
    op.drop_index("ix_goods_receipt_items_goods_receipt_id", table_name="goods_receipt_items")
    op.drop_table("goods_receipt_items")

    op.drop_index("ix_goods_receipts_warehouse_id", table_name="goods_receipts")
    op.drop_index("ix_goods_receipts_receipt_date", table_name="goods_receipts")
    op.drop_index("ix_goods_receipts_purchase_order_id", table_name="goods_receipts")
    op.drop_index(op.f("ix_goods_receipts_code"), table_name="goods_receipts")
    op.drop_table("goods_receipts")

    op.drop_index("ix_purchase_order_items_purchase_order_id", table_name="purchase_order_items")
    op.drop_index("ix_purchase_order_items_product_id", table_name="purchase_order_items")
    op.drop_table("purchase_order_items")

    op.drop_index("ix_purchase_orders_supplier_id", table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_status", table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_issue_date", table_name="purchase_orders")
    op.drop_index(op.f("ix_purchase_orders_code"), table_name="purchase_orders")
    op.drop_table("purchase_orders")

    op.drop_index(op.f("ix_suppliers_tax_id"), table_name="suppliers")
    op.drop_index("ix_suppliers_company_name", table_name="suppliers")
    op.drop_table("suppliers")

    postgresql.ENUM(
        *SUPPLIER_BILL_STATUS_VALUES, name="supplier_bill_status"
    ).drop(bind, checkfirst=True)
    postgresql.ENUM(
        *PURCHASE_ORDER_STATUS_VALUES, name="purchase_order_status"
    ).drop(bind, checkfirst=True)
