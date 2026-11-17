"""purchasing: historial de pagos de facturas de proveedor

Revision ID: 20261117_0003
Revises: 8797b4f029dc
Create Date: 2026-11-17 20:00:00+00:00

Materializa en ``supplier_bill_payments`` cada abono aplicado a una cuenta por
pagar. ``SupplierBill.balance_due`` sigue siendo el saldo vigente, pero el
historial permite auditar los pagos parciales y totales sin reconstruirlos.

- FK ``bill_id → supplier_bills.id`` con ``ON DELETE RESTRICT`` (inmutabilidad
  financiera del manifiesto, sección 4).
- ``amount`` ``Numeric(14, 2)`` con ``CHECK (amount > 0)``.
- ``paid_at`` (fecha comercial), ``reference`` (comprobante) y ``created_at``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261117_0003"
down_revision: str | None = "8797b4f029dc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "supplier_bill_payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("bill_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column(
            "paid_at",
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
        sa.CheckConstraint(
            "amount > 0", name="ck_supplier_bill_payments_amount_positive"
        ),
        sa.ForeignKeyConstraint(
            ["bill_id"], ["supplier_bills.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_supplier_bill_payments_bill_id",
        "supplier_bill_payments",
        ["bill_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("supplier_bill_payments")
