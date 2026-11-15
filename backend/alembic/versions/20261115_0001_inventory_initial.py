"""inventory: esquema inicial

Revision ID: 20261115_0001
Revises:
Create Date: 2026-11-15 00:00:00+00:00

Crea el esquema del módulo de Inventario conforme a
``specs/inventory_spec.md`` (sección 2) y a
``backend/src/modules/inventory/models.py``:

- enum nativo ``movement_type``
- ``warehouses`` y ``products`` con sus índices únicos
- ``stocks`` (saldo producto–almacén, único por par)
- ``stock_movements`` (histórico inmutable)
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261115_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MOVEMENT_TYPE_VALUES = ("INBOUND", "OUTBOUND", "TRANSFER", "ADJUSTMENT")


def _movement_type_enum() -> postgresql.ENUM:
    """Tipo enum reutilizable que no intenta crear el tipo por segunda vez."""
    return postgresql.ENUM(
        *MOVEMENT_TYPE_VALUES,
        name="movement_type",
        create_type=False,
    )


def upgrade() -> None:
    bind = op.get_bind()

    # El enum nativo debe existir antes de la tabla que lo usa.
    postgresql.ENUM(*MOVEMENT_TYPE_VALUES, name="movement_type").create(
        bind, checkfirst=True
    )

    op.create_table(
        "warehouses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("address", sa.String(length=255), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_warehouses_code", "warehouses", ["code"], unique=True)

    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sku", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column(
            "minimum_stock",
            sa.Integer(),
            server_default=sa.text("5"),
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_products_sku", "products", ["sku"], unique=True)

    op.create_table(
        "stocks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_id", sa.Integer(), nullable=False),
        sa.Column(
            "quantity",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_id"], ["warehouses.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "product_id",
            "warehouse_id",
            name="uq_stocks_product_warehouse",
        ),
    )
    op.create_index("ix_stocks_product_id", "stocks", ["product_id"])
    op.create_index("ix_stocks_warehouse_id", "stocks", ["warehouse_id"])

    op.create_table(
        "stock_movements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("warehouse_source_id", sa.Integer(), nullable=True),
        sa.Column("warehouse_destination_id", sa.Integer(), nullable=True),
        sa.Column("movement_type", _movement_type_enum(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("reference_document", sa.String(length=100), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=150), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "quantity > 0", name="ck_stock_movements_quantity_positive"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_destination_id"],
            ["warehouses.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["warehouse_source_id"],
            ["warehouses.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_stock_movements_created_at", "stock_movements", ["created_at"]
    )
    op.create_index(
        "ix_stock_movements_product_created_at",
        "stock_movements",
        ["product_id", "created_at"],
    )
    op.create_index(
        "ix_stock_movements_warehouse_destination_id",
        "stock_movements",
        ["warehouse_destination_id"],
    )
    op.create_index(
        "ix_stock_movements_warehouse_source_id",
        "stock_movements",
        ["warehouse_source_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Orden inverso: primero el histórico, luego saldos, catálogo y enum.
    op.drop_table("stock_movements")
    op.drop_table("stocks")
    op.drop_table("products")
    op.drop_table("warehouses")

    postgresql.ENUM(*MOVEMENT_TYPE_VALUES, name="movement_type").drop(
        bind, checkfirst=True
    )
