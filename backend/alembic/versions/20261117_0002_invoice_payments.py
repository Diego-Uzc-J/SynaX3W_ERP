"""sales: historial de pagos de facturas

Revision ID: 20261117_0002
Revises: 20261117_0001
Create Date: 2026-11-17 00:30:00+00:00

Materializa en ``invoice_payments`` cada abono aplicado a una factura.
``Invoice.balance_due`` sigue siendo el saldo vigente, pero el historial
permite auditar pagos parciales y totales sin reconstruirlos desde el saldo.

- FK ``invoice_id → invoices.id`` con ``ON DELETE RESTRICT``.
- ``amount`` ``Numeric(14, 2)`` con ``CHECK (amount > 0)``.
- ``paid_at`` (fecha comercial) y ``created_at`` (auditoría).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261117_0002"
down_revision: str | None = "20261117_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "invoice_payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("invoice_id", sa.Integer(), nullable=False),
        sa.Column(
            "amount", sa.Numeric(precision=14, scale=2), nullable=False
        ),
        sa.Column(
            "paid_at",
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
        sa.CheckConstraint(
            "amount > 0", name="ck_invoice_payments_amount_positive"
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"], ["invoices.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_invoice_payments_invoice_id",
        "invoice_payments",
        ["invoice_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("invoice_payments")
