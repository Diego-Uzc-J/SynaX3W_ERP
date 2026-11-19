"""accounting: esquema inicial

Revision ID: ff363bda84aa
Revises: 20261117_0003
Create Date: 2026-11-19 19:49:28.618723+00:00

Crea el esquema del módulo de Finanzas y Contabilidad conforme a
``specs/accounting_spec.md`` (sección 2) y a
``backend/src/modules/accounting/models.py``:

- enums nativos ``account_type``, ``journal_entry_status`` y
  ``account_balance_status``
- plan de cuentas ``accounts`` (jerárquico) y libro diario
  ``journal_entries`` / ``journal_items``
- cartera ``account_receivables`` (CxC) y ``account_payables`` (CxP), con su
  historial de abonos ``payment_records``
- control de periodos ``accounting_periods``

Los tipos enum se crean y eliminan explícitamente, igual que en las migraciones
de ``sales`` y ``purchasing``, para que el ciclo ``upgrade`` / ``downgrade`` sea
repetible en PostgreSQL.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ff363bda84aa"
down_revision: str | None = "20261117_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACCOUNT_TYPE_VALUES = (
    "ASSET",
    "LIABILITY",
    "EQUITY",
    "REVENUE",
    "EXPENSE",
)

JOURNAL_ENTRY_STATUS_VALUES = (
    "DRAFT",
    "POSTED",
    "VOID",
)

ACCOUNT_BALANCE_STATUS_VALUES = (
    "PENDING",
    "PARTIALLY_PAID",
    "PAID",
    "OVERDUE",
)


def _account_type_enum() -> postgresql.ENUM:
    """Tipo enum reutilizable que no intenta crear el tipo por segunda vez."""
    return postgresql.ENUM(*ACCOUNT_TYPE_VALUES, name="account_type", create_type=False)


def _journal_entry_status_enum() -> postgresql.ENUM:
    """Tipo enum reutilizable que no intenta crear el tipo por segunda vez."""
    return postgresql.ENUM(
        *JOURNAL_ENTRY_STATUS_VALUES,
        name="journal_entry_status",
        create_type=False,
    )


def _account_balance_status_enum() -> postgresql.ENUM:
    """Tipo enum reutilizable que no intenta crear el tipo por segunda vez."""
    return postgresql.ENUM(
        *ACCOUNT_BALANCE_STATUS_VALUES,
        name="account_balance_status",
        create_type=False,
    )


def upgrade() -> None:
    bind = op.get_bind()

    # Los enums nativos deben existir antes de las tablas que los usan.
    postgresql.ENUM(*ACCOUNT_TYPE_VALUES, name="account_type").create(
        bind, checkfirst=True
    )
    postgresql.ENUM(*JOURNAL_ENTRY_STATUS_VALUES, name="journal_entry_status").create(
        bind, checkfirst=True
    )
    postgresql.ENUM(
        *ACCOUNT_BALANCE_STATUS_VALUES, name="account_balance_status"
    ).create(bind, checkfirst=True)

    op.create_table(
        "accounting_periods",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=20), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("is_closed", sa.Boolean(), server_default="false", nullable=False),
        sa.CheckConstraint(
            "start_date <= end_date", name="ck_accounting_periods_valid_range"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_accounting_periods_end_date", "accounting_periods", ["end_date"], unique=False
    )
    op.create_index(
        op.f("ix_accounting_periods_name"),
        "accounting_periods",
        ["name"],
        unique=True,
    )
    op.create_index(
        "ix_accounting_periods_start_date",
        "accounting_periods",
        ["start_date"],
        unique=False,
    )

    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("account_type", _account_type_enum(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["parent_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_accounts_account_type", "accounts", ["account_type"], unique=False)
    op.create_index(op.f("ix_accounts_code"), "accounts", ["code"], unique=True)
    op.create_index("ix_accounts_name", "accounts", ["name"], unique=False)
    op.create_index("ix_accounts_parent_id", "accounts", ["parent_id"], unique=False)

    op.create_table(
        "journal_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column(
            "entry_date",
            sa.Date(),
            server_default=sa.text("CURRENT_DATE"),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("reference_document", sa.String(length=100), nullable=True),
        sa.Column(
            "status",
            _journal_entry_status_enum(),
            server_default=sa.text("'DRAFT'"),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(length=150), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_journal_entries_code"), "journal_entries", ["code"], unique=True)
    op.create_index(
        "ix_journal_entries_created_by", "journal_entries", ["created_by"], unique=False
    )
    op.create_index(
        "ix_journal_entries_entry_date", "journal_entries", ["entry_date"], unique=False
    )
    op.create_index("ix_journal_entries_status", "journal_entries", ["status"], unique=False)

    op.create_table(
        "account_payables",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("bill_reference", sa.String(length=100), nullable=False),
        sa.Column("journal_entry_id", sa.Integer(), nullable=True),
        sa.Column("total_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "paid_amount",
            sa.Numeric(precision=14, scale=2),
            server_default=sa.text("0.00"),
            nullable=False,
        ),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            _account_balance_status_enum(),
            server_default=sa.text("'PENDING'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "paid_amount <= total_amount",
            name="ck_account_payables_paid_not_over_total",
        ),
        sa.CheckConstraint(
            "paid_amount >= 0", name="ck_account_payables_paid_non_negative"
        ),
        sa.CheckConstraint(
            "total_amount >= 0", name="ck_account_payables_total_non_negative"
        ),
        sa.ForeignKeyConstraint(
            ["journal_entry_id"], ["journal_entries.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id"], ["suppliers.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_account_payables_due_date", "account_payables", ["due_date"], unique=False
    )
    op.create_index(
        "ix_account_payables_journal_entry_id",
        "account_payables",
        ["journal_entry_id"],
        unique=False,
    )
    op.create_index(
        "ix_account_payables_status", "account_payables", ["status"], unique=False
    )
    op.create_index(
        "ix_account_payables_supplier_id",
        "account_payables",
        ["supplier_id"],
        unique=False,
    )

    op.create_table(
        "journal_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("journal_entry_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column(
            "debit",
            sa.Numeric(precision=14, scale=2),
            server_default=sa.text("0.00"),
            nullable=False,
        ),
        sa.Column(
            "credit",
            sa.Numeric(precision=14, scale=2),
            server_default=sa.text("0.00"),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "NOT (debit > 0 AND credit > 0)", name="ck_journal_items_single_side"
        ),
        sa.CheckConstraint(
            "credit >= 0", name="ck_journal_items_credit_non_negative"
        ),
        sa.CheckConstraint("debit >= 0", name="ck_journal_items_debit_non_negative"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["journal_entry_id"], ["journal_entries.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_journal_items_account_id", "journal_items", ["account_id"], unique=False
    )
    op.create_index(
        "ix_journal_items_journal_entry_id",
        "journal_items",
        ["journal_entry_id"],
        unique=False,
    )

    op.create_table(
        "account_receivables",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("invoice_id", sa.Integer(), nullable=True),
        sa.Column("journal_entry_id", sa.Integer(), nullable=True),
        sa.Column("total_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "paid_amount",
            sa.Numeric(precision=14, scale=2),
            server_default=sa.text("0.00"),
            nullable=False,
        ),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            _account_balance_status_enum(),
            server_default=sa.text("'PENDING'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "paid_amount <= total_amount",
            name="ck_account_receivables_paid_not_over_total",
        ),
        sa.CheckConstraint(
            "paid_amount >= 0", name="ck_account_receivables_paid_non_negative"
        ),
        sa.CheckConstraint(
            "total_amount >= 0", name="ck_account_receivables_total_non_negative"
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["customers.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["journal_entry_id"], ["journal_entries.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_account_receivables_customer_id",
        "account_receivables",
        ["customer_id"],
        unique=False,
    )
    op.create_index(
        "ix_account_receivables_due_date",
        "account_receivables",
        ["due_date"],
        unique=False,
    )
    op.create_index(
        "ix_account_receivables_invoice_id",
        "account_receivables",
        ["invoice_id"],
        unique=False,
    )
    op.create_index(
        "ix_account_receivables_journal_entry_id",
        "account_receivables",
        ["journal_entry_id"],
        unique=False,
    )
    op.create_index(
        "ix_account_receivables_status",
        "account_receivables",
        ["status"],
        unique=False,
    )

    op.create_table(
        "payment_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("receivable_id", sa.Integer(), nullable=True),
        sa.Column("payable_id", sa.Integer(), nullable=True),
        sa.Column("journal_entry_id", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "payment_date",
            sa.Date(),
            server_default=sa.text("CURRENT_DATE"),
            nullable=False,
        ),
        sa.Column("reference", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount > 0", name="ck_payment_records_amount_positive"),
        sa.CheckConstraint(
            "receivable_id IS NOT NULL OR payable_id IS NOT NULL",
            name="ck_payment_records_has_target",
        ),
        sa.CheckConstraint(
            "NOT (receivable_id IS NOT NULL AND payable_id IS NOT NULL)",
            name="ck_payment_records_single_target",
        ),
        sa.ForeignKeyConstraint(
            ["journal_entry_id"], ["journal_entries.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["payable_id"], ["account_payables.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["receivable_id"], ["account_receivables.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_payment_records_journal_entry_id",
        "payment_records",
        ["journal_entry_id"],
        unique=False,
    )
    op.create_index(
        "ix_payment_records_payable_id",
        "payment_records",
        ["payable_id"],
        unique=False,
    )
    op.create_index(
        "ix_payment_records_payment_date",
        "payment_records",
        ["payment_date"],
        unique=False,
    )
    op.create_index(
        "ix_payment_records_receivable_id",
        "payment_records",
        ["receivable_id"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Orden inverso: abonos, cartera, líneas de asiento, asientos, cuentas y
    # periodos. Los tipos enum se eliminan al final, cuando nadie los usa.
    op.drop_index("ix_payment_records_receivable_id", table_name="payment_records")
    op.drop_index("ix_payment_records_payment_date", table_name="payment_records")
    op.drop_index("ix_payment_records_payable_id", table_name="payment_records")
    op.drop_index("ix_payment_records_journal_entry_id", table_name="payment_records")
    op.drop_table("payment_records")

    op.drop_index("ix_account_receivables_status", table_name="account_receivables")
    op.drop_index(
        "ix_account_receivables_journal_entry_id", table_name="account_receivables"
    )
    op.drop_index("ix_account_receivables_invoice_id", table_name="account_receivables")
    op.drop_index("ix_account_receivables_due_date", table_name="account_receivables")
    op.drop_index("ix_account_receivables_customer_id", table_name="account_receivables")
    op.drop_table("account_receivables")

    op.drop_index("ix_journal_items_journal_entry_id", table_name="journal_items")
    op.drop_index("ix_journal_items_account_id", table_name="journal_items")
    op.drop_table("journal_items")

    op.drop_index("ix_account_payables_supplier_id", table_name="account_payables")
    op.drop_index("ix_account_payables_status", table_name="account_payables")
    op.drop_index(
        "ix_account_payables_journal_entry_id", table_name="account_payables"
    )
    op.drop_index("ix_account_payables_due_date", table_name="account_payables")
    op.drop_table("account_payables")

    op.drop_index("ix_journal_entries_status", table_name="journal_entries")
    op.drop_index("ix_journal_entries_entry_date", table_name="journal_entries")
    op.drop_index("ix_journal_entries_created_by", table_name="journal_entries")
    op.drop_index(op.f("ix_journal_entries_code"), table_name="journal_entries")
    op.drop_table("journal_entries")

    op.drop_index("ix_accounts_parent_id", table_name="accounts")
    op.drop_index("ix_accounts_name", table_name="accounts")
    op.drop_index(op.f("ix_accounts_code"), table_name="accounts")
    op.drop_index("ix_accounts_account_type", table_name="accounts")
    op.drop_table("accounts")

    op.drop_index("ix_accounting_periods_start_date", table_name="accounting_periods")
    op.drop_index(op.f("ix_accounting_periods_name"), table_name="accounting_periods")
    op.drop_index("ix_accounting_periods_end_date", table_name="accounting_periods")
    op.drop_table("accounting_periods")

    postgresql.ENUM(
        *ACCOUNT_BALANCE_STATUS_VALUES, name="account_balance_status"
    ).drop(bind, checkfirst=True)
    postgresql.ENUM(*JOURNAL_ENTRY_STATUS_VALUES, name="journal_entry_status").drop(
        bind, checkfirst=True
    )
    postgresql.ENUM(*ACCOUNT_TYPE_VALUES, name="account_type").drop(
        bind, checkfirst=True
    )
