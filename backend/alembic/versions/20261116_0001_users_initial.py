"""users: esquema inicial

Revision ID: 20261116_0001
Revises: 20261115_0001
Create Date: 2026-11-16 00:00:00+00:00

Crea el esquema del módulo de Usuarios, Roles y Seguridad conforme a
``specs/users_spec.md`` (sección 3) y a
``backend/src/modules/users/models.py``:

- enum nativo ``role_enum`` con los siete perfiles en minúsculas
- ``roles`` (catálogo maestro con ``allowed_modules`` en JSONB)
- ``users`` (identidad, credenciales y control de bloqueo por fuerza bruta)
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261116_0001"
down_revision: str | None = "20261115_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE_ENUM_VALUES = (
    "administrator",
    "inventory",
    "sales",
    "purchasing",
    "accounting",
    "hr",
    "manufacturing",
)


def _role_enum() -> postgresql.ENUM:
    """Tipo enum reutilizable que no intenta crear el tipo por segunda vez."""
    return postgresql.ENUM(
        *ROLE_ENUM_VALUES,
        name="role_enum",
        create_type=False,
    )


def upgrade() -> None:
    bind = op.get_bind()

    # El enum nativo debe existir antes de las tablas que lo usan.
    postgresql.ENUM(*ROLE_ENUM_VALUES, name="role_enum").create(
        bind, checkfirst=True
    )

    op.create_table(
        "roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", _role_enum(), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column(
            "allowed_modules",
            postgresql.JSONB(astext_type=sa.Text()),
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
    op.create_index("ix_roles_name", "roles", ["name"], unique=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("full_name", sa.String(length=150), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "failed_login_attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_index("ix_users_role_id", "users", ["role_id"])


def downgrade() -> None:
    bind = op.get_bind()

    # Orden inverso: primero los usuarios, luego el catálogo y el enum.
    op.drop_table("users")
    op.drop_table("roles")

    postgresql.ENUM(*ROLE_ENUM_VALUES, name="role_enum").drop(
        bind, checkfirst=True
    )
