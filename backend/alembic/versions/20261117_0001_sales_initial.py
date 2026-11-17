"""sales: esquema inicial

Revision ID: 20261117_0001
Revises: 20261116_0001
Create Date: 2026-11-17 00:00:00+00:00

Crea el esquema del módulo de Ventas y Facturación conforme a
``specs/sales_spec.md`` (sección 2) y a
``backend/src/modules/sales/models.py``:

- enums nativos ``sales_order_status`` e ``invoice_status``
- ``customers`` (identidad fiscal y límite de crédito)
- ``sales_orders`` y ``sales_order_items`` (pedidos/cotizaciones y sus líneas)
- ``invoices`` (documento fiscal con saldo pendiente)
- ``credit_notes`` (contrapartida por devoluciones o ajustes)
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261117_0001"
down_revision: str | None = "20261116_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SALES_ORDER_STATUS_VALUES = (
    "DRAFT",
    "QUOTATION",
    "CONFIRMED",
    "FULFILLED",
    "CANCELLED",
)

INVOICE_STATUS_VALUES = ("ISSUED", "PAID", "VOID")


def _sales_order_status_enum() -> postgresql.ENUM:
    """Tipo enum reutilizable que no intenta crear el tipo por segunda vez."""
    return postgresql.ENUM(
        *SALES_ORDER_STATUS_VALUES,
        name="sales_order_status",
        create_type=False,
    )


def _invoice_status_enum() -> postgresql.ENUM:
    """Tipo enum reutilizable que no intenta crear el tipo por segunda vez."""
    return postgresql.ENUM(
        *INVOICE_STATUS_VALUES,
        name="invoice_status",
        create_type=False,
    )


def upgrade() -> None:
    bind = op.get_bind()

    # Los enums nativos deben existir antes de las tablas que los usan.
    postgresql.ENUM(
        *SALES_ORDER_STATUS_VALUES, name="sales_order_status"
    ).create(bind, checkfirst=True)
    postgresql.ENUM(*INVOICE_STATUS_VALUES, name="invoice_status").create(
        bind, checkfirst=True
    )

    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tax_id", sa.String(length=50), nullable=False),
        sa.Column("company_name", sa.String(length=200), nullable=False),
        sa.Column("contact_name", sa.String(length=150), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("address", sa.String(length=255), nullable=False),
        sa.Column(
            "credit_limit",
            sa.Numeric(precision=14, scale=2),
            server_default=sa.text("0.00"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "credit_limit >= 0", name="ck_customers_credit_limit_non_negative"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_customers_tax_id", "customers", ["tax_id"], unique=True)
    op.create_index(
        "ix_customers_company_name", "customers", ["company_name"], unique=False
    )

    op.create_table(
        "sales_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            _sales_order_status_enum(),
            server_default=sa.text("'DRAFT'"),
            nullable=False,
        ),
        sa.Column(
            "issue_date",
            sa.Date(),
            server_default=sa.text("CURRENT_DATE"),
            nullable=False,
        ),
        sa.Column("valid_until", sa.Date(), nullable=True),
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
            "subtotal >= 0", name="ck_sales_orders_subtotal_non_negative"
        ),
        sa.CheckConstraint(
            "tax_amount >= 0", name="ck_sales_orders_tax_amount_non_negative"
        ),
        sa.CheckConstraint("total >= 0", name="ck_sales_orders_total_non_negative"),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["customers.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sales_orders_code", "sales_orders", ["code"], unique=True)
    op.create_index(
        "ix_sales_orders_customer_id", "sales_orders", ["customer_id"], unique=False
    )
    op.create_index(
        "ix_sales_orders_status", "sales_orders", ["status"], unique=False
    )

    op.create_table(
        "sales_order_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sales_order_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "tax_rate",
            sa.Numeric(precision=5, scale=2),
            server_default=sa.text("0.00"),
            nullable=False,
        ),
        sa.Column("subtotal", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.CheckConstraint(
            "quantity > 0", name="ck_sales_order_items_quantity_positive"
        ),
        sa.CheckConstraint(
            "unit_price >= 0", name="ck_sales_order_items_unit_price_non_negative"
        ),
        sa.CheckConstraint(
            "tax_rate >= 0 AND tax_rate <= 100",
            name="ck_sales_order_items_tax_rate_range",
        ),
        sa.CheckConstraint(
            "subtotal >= 0", name="ck_sales_order_items_subtotal_non_negative"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["sales_order_id"], ["sales_orders.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sales_order_items_product_id",
        "sales_order_items",
        ["product_id"],
        unique=False,
    )
    op.create_index(
        "ix_sales_order_items_sales_order_id",
        "sales_order_items",
        ["sales_order_id"],
        unique=False,
    )

    op.create_table(
        "invoices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("sales_order_id", sa.Integer(), nullable=True),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            _invoice_status_enum(),
            server_default=sa.text("'ISSUED'"),
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
        sa.CheckConstraint("total >= 0", name="ck_invoices_total_non_negative"),
        sa.CheckConstraint(
            "balance_due >= 0", name="ck_invoices_balance_due_non_negative"
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["customers.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["sales_order_id"], ["sales_orders.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_invoices_code", "invoices", ["code"], unique=True)
    op.create_index(
        "ix_invoices_customer_id", "invoices", ["customer_id"], unique=False
    )
    op.create_index(
        "ix_invoices_sales_order_id", "invoices", ["sales_order_id"], unique=False
    )
    op.create_index("ix_invoices_status", "invoices", ["status"], unique=False)

    op.create_table(
        "credit_notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("invoice_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "issue_date",
            sa.Date(),
            server_default=sa.text("CURRENT_DATE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount > 0", name="ck_credit_notes_amount_positive"),
        sa.ForeignKeyConstraint(
            ["invoice_id"], ["invoices.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_credit_notes_code", "credit_notes", ["code"], unique=True)
    op.create_index(
        "ix_credit_notes_invoice_id", "credit_notes", ["invoice_id"], unique=False
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Orden inverso: contrapartidas, facturas, líneas, pedidos y clientes.
    op.drop_table("credit_notes")
    op.drop_table("invoices")
    op.drop_table("sales_order_items")
    op.drop_table("sales_orders")
    op.drop_table("customers")

    postgresql.ENUM(*INVOICE_STATUS_VALUES, name="invoice_status").drop(
        bind, checkfirst=True
    )
    postgresql.ENUM(
        *SALES_ORDER_STATUS_VALUES, name="sales_order_status"
    ).drop(bind, checkfirst=True)
