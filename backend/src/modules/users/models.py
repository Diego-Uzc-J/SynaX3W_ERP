"""Modelos de dominio del módulo de Usuarios, Roles y Seguridad.

Implementa las entidades descritas en ``specs/users_spec.md`` (sección 3):

- ``RoleEnum``: perfiles de acceso estáticos del ERP. Los nombres de los
  miembros van en mayúsculas, pero el valor persistido es el nombre técnico en
  minúsculas (``administrator``, ``inventory``, ...), tal como exige el
  *seeding* de la especificación.
- ``Role``: catálogo maestro de roles con los módulos permitidos.
- ``User``: identidad del colaborador, credenciales y control de bloqueo por
  fuerza bruta.

La clase declarativa ``Base`` es transversal y vive en ``src.core.database``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from src.core.database import Base


class RoleEnum(str, PyEnum):
    """Perfiles de acceso estáticos del ERP (sección 3.1 de la especificación)."""

    ADMINISTRATOR = "administrator"
    INVENTORY = "inventory"
    SALES = "sales"
    PURCHASING = "purchasing"
    ACCOUNTING = "accounting"
    HR = "hr"
    MANUFACTURING = "manufacturing"


def _role_enum_values(enum_cls: type[RoleEnum]) -> list[str]:
    """Persiste ``RoleEnum.ADMINISTRATOR`` como ``"administrator"``.

    Sin ``values_callable`` SQLAlchemy guardaría el *nombre* del miembro
    (``ADMINISTRATOR``), que no corresponde al contrato de la especificación.
    """
    return [member.value for member in enum_cls]


#: Tipo enum nativo reutilizable, con valores en minúsculas.
ROLE_ENUM_TYPE = SAEnum(
    RoleEnum,
    name="role_enum",
    native_enum=True,
    validate_strings=True,
    values_callable=_role_enum_values,
)

#: JSONB en PostgreSQL y JSON genérico en dialectos de prueba (SQLite).
ALLOWED_MODULES_TYPE = JSONB().with_variant(JSON(), "sqlite")


class Role(Base):
    """Rol funcional y matriz de módulos a los que permite acceder."""

    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[RoleEnum] = mapped_column(
        ROLE_ENUM_TYPE, unique=True, nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    allowed_modules: Mapped[list[str]] = mapped_column(
        ALLOWED_MODULES_TYPE, nullable=False, default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    users: Mapped[list[User]] = relationship(back_populates="role")

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return f"<Role id={self.id!r} name={self.name!r}>"


class User(Base):
    """Cuenta de un colaborador con credenciales y control de bloqueo."""

    __tablename__ = "users"
    __table_args__ = (Index("ix_users_role_id", "role_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    username: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="RESTRICT"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    role: Mapped[Role] = relationship(back_populates="users")

    @validates("email")
    def _normalize_email(self, _key: str, value: str) -> str:
        """Normaliza el correo a minúsculas (sección 3.3)."""
        return value.strip().lower()

    @validates("username")
    def _normalize_username(self, _key: str, value: str) -> str:
        """Elimina espacios accidentales del nombre de usuario."""
        return value.strip()

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return f"<User id={self.id!r} email={self.email!r} role_id={self.role_id!r}>"
