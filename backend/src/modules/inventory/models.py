"""Modelos de dominio del módulo de Inventario y Logística.

Implementa las entidades descritas en ``specs/inventory_spec.md`` (sección 2):
``Warehouse``, ``Product``, ``Stock`` y ``StockMovement``.

La clase declarativa ``Base`` es transversal y vive en ``src.core.database``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base


class MovementType(str, PyEnum):
    """Tipos de movimiento de inventario soportados."""

    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"
    TRANSFER = "TRANSFER"
    ADJUSTMENT = "ADJUSTMENT"


class Warehouse(Base):
    """Almacén o bodega, física o lógica, donde se resguarda inventario."""

    __tablename__ = "warehouses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Existencias mantenidas en este almacén.
    stocks: Mapped[list[Stock]] = relationship(
        back_populates="warehouse",
        cascade="all, delete-orphan",
    )
    # Movimientos en los que este almacén actúa como origen o destino.
    outgoing_movements: Mapped[list[StockMovement]] = relationship(
        back_populates="warehouse_source",
        foreign_keys="StockMovement.warehouse_source_id",
    )
    incoming_movements: Mapped[list[StockMovement]] = relationship(
        back_populates="warehouse_destination",
        foreign_keys="StockMovement.warehouse_destination_id",
    )

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return f"<Warehouse id={self.id!r} code={self.code!r}>"


class Product(Base):
    """Artículo o SKU gestionado por el inventario."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    minimum_stock: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5, server_default="5"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Saldos del producto por almacén y su historial de movimientos.
    stocks: Mapped[list[Stock]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
    )
    # Sin cascade de borrado: el historial de movimientos es inmutable.
    movements: Mapped[list[StockMovement]] = relationship(back_populates="product")

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return f"<Product id={self.id!r} sku={self.sku!r}>"


class Stock(Base):
    """Saldo actual de un producto en un almacén concreto.

    Materializa la relación muchos-a-muchos entre ``Product`` y ``Warehouse``.
    """

    __tablename__ = "stocks"
    __table_args__ = (
        UniqueConstraint(
            "product_id", "warehouse_id", name="uq_stocks_product_warehouse"
        ),
        Index("ix_stocks_warehouse_id", "warehouse_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    product: Mapped[Product] = relationship(back_populates="stocks")
    warehouse: Mapped[Warehouse] = relationship(back_populates="stocks")

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return (
            f"<Stock product_id={self.product_id!r} "
            f"warehouse_id={self.warehouse_id!r} quantity={self.quantity!r}>"
        )


class StockMovement(Base):
    """Registro histórico e inmutable de un cambio de existencias.

    La inmutabilidad (regla de negocio 3) se garantiza en la capa de servicio:
    este modelo no expone actualizaciones ni borrados; toda corrección debe
    registrarse como un nuevo movimiento ``ADJUSTMENT``.
    """

    __tablename__ = "stock_movements"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_stock_movements_quantity_positive"),
        Index(
            "ix_stock_movements_product_created_at",
            "product_id",
            "created_at",
        ),
        Index("ix_stock_movements_warehouse_source_id", "warehouse_source_id"),
        Index("ix_stock_movements_warehouse_destination_id", "warehouse_destination_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    warehouse_source_id: Mapped[int | None] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=True
    )
    warehouse_destination_id: Mapped[int | None] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=True
    )
    movement_type: Mapped[MovementType] = mapped_column(
        SAEnum(
            MovementType,
            name="movement_type",
            native_enum=True,
            validate_strings=True,
        ),
        nullable=False,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    reference_document: Mapped[str] = mapped_column(String(100), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(150), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    product: Mapped[Product] = relationship(back_populates="movements")
    warehouse_source: Mapped[Warehouse | None] = relationship(
        back_populates="outgoing_movements",
        foreign_keys=[warehouse_source_id],
    )
    warehouse_destination: Mapped[Warehouse | None] = relationship(
        back_populates="incoming_movements",
        foreign_keys=[warehouse_destination_id],
    )

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return (
            f"<StockMovement id={self.id!r} type={self.movement_type!r} "
            f"quantity={self.quantity!r}>"
        )
