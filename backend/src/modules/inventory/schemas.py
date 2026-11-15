"""Esquemas Pydantic v2 del módulo de Inventario y Logística.

Derivados de ``specs/inventory_spec.md`` (sección 2) y de los modelos ORM de
``src.modules.inventory.models``. Se definen contratos de entrada (``Create``),
actualización parcial (``Update``) y salida (``Response``) para productos y
almacenes, además de la creación y respuesta de movimientos de stock.

``StockMovement`` no expone un esquema ``Update`` a propósito: el historial es
inmutable (regla de negocio 3) y toda corrección se registra como un nuevo
movimiento de tipo ``ADJUSTMENT``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.modules.inventory.models import MovementType

__all__ = [
    "MovementType",
    "ProductCreate",
    "ProductResponse",
    "ProductUpdate",
    "StockMovementCreate",
    "StockMovementResponse",
    "StockResponse",
    "WarehouseCreate",
    "WarehouseResponse",
    "WarehouseUpdate",
]


class WarehouseBase(BaseModel):
    """Atributos comunes de un almacén o bodega."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    code: str = Field(
        min_length=1,
        max_length=50,
        description="Código único del almacén.",
        examples=["BOD-MED-01"],
    )
    name: str = Field(
        min_length=1,
        max_length=150,
        description="Nombre descriptivo del almacén.",
        examples=["Bodega Principal Medellín"],
    )
    address: str | None = Field(
        default=None,
        max_length=255,
        description="Dirección física del almacén (opcional).",
    )
    is_active: bool = Field(
        default=True, description="Indica si el almacén está operativo."
    )


class WarehouseCreate(WarehouseBase):
    """Datos requeridos para registrar un almacén."""


class WarehouseUpdate(BaseModel):
    """Actualización parcial de un almacén (PATCH)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=150)
    address: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None

    @model_validator(mode="after")
    def _validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Debe enviar al menos un campo para actualizar")
        for field in ("code", "name", "is_active"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"El campo '{field}' no puede ser nulo")
        return self


class WarehouseResponse(WarehouseBase):
    """Representación de salida de un almacén."""

    model_config = ConfigDict(
        str_strip_whitespace=True, extra="forbid", from_attributes=True
    )

    id: int
    created_at: datetime


class ProductBase(BaseModel):
    """Atributos comunes de un producto (SKU)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    sku: str = Field(
        min_length=1,
        max_length=50,
        description="Código SKU único en todo el ERP.",
        examples=["LAP-IND-001"],
    )
    name: str = Field(
        min_length=1,
        max_length=200,
        description="Nombre comercial del producto.",
        examples=["Laptop Industrial Rugged"],
    )
    description: str | None = Field(
        default=None, description="Descripción detallada (opcional)."
    )
    unit_price: Decimal = Field(
        ge=0,
        max_digits=12,
        decimal_places=2,
        description="Precio base de costo o venta.",
        examples=["1899.90"],
    )
    minimum_stock: int = Field(
        default=5,
        ge=0,
        description="Umbral mínimo para alertas de reabastecimiento.",
    )
    is_active: bool = Field(
        default=True, description="Indica si el producto está vigente."
    )


class ProductCreate(ProductBase):
    """Datos requeridos para crear un producto."""


class ProductUpdate(BaseModel):
    """Actualización parcial de un producto (PATCH)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    sku: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    unit_price: Decimal | None = Field(
        default=None, ge=0, max_digits=12, decimal_places=2
    )
    minimum_stock: int | None = Field(default=None, ge=0)
    is_active: bool | None = None

    @model_validator(mode="after")
    def _validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("Debe enviar al menos un campo para actualizar")
        for field in ("sku", "name", "unit_price", "minimum_stock", "is_active"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"El campo '{field}' no puede ser nulo")
        return self


class ProductResponse(ProductBase):
    """Representación de salida de un producto."""

    model_config = ConfigDict(
        str_strip_whitespace=True, extra="forbid", from_attributes=True
    )

    id: int
    created_at: datetime


class StockMovementBase(BaseModel):
    """Atributos comunes de un movimiento de inventario."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    product_id: int = Field(gt=0, description="Producto afectado por el movimiento.")
    warehouse_source_id: int | None = Field(
        default=None,
        gt=0,
        description="Bodega de origen (nula en entradas puras).",
    )
    warehouse_destination_id: int | None = Field(
        default=None,
        gt=0,
        description="Bodega de destino (nula en salidas puras).",
    )
    movement_type: MovementType = Field(
        description="Tipo de movimiento: INBOUND, OUTBOUND, TRANSFER o ADJUSTMENT."
    )
    quantity: int = Field(
        gt=0,
        description="Cantidad movida; siempre mayor que cero.",
        examples=[10],
    )
    reference_document: str = Field(
        min_length=1,
        max_length=100,
        description="Documento de referencia (orden de compra, factura, etc.).",
        examples=["OC-2026-001", "FAC-8921"],
    )
    notes: str | None = Field(default=None, description="Observaciones (opcional).")
    created_by: str = Field(
        min_length=1,
        max_length=150,
        description="Identificador del usuario que registra el movimiento.",
    )

    @model_validator(mode="after")
    def _validate_movement(self) -> Self:
        source = self.warehouse_source_id
        destination = self.warehouse_destination_id

        if self.movement_type == MovementType.TRANSFER:
            if source is None or destination is None:
                raise ValueError(
                    "Una transferencia requiere bodega de origen y de destino"
                )
            if source == destination:
                raise ValueError(
                    "La bodega de origen y la de destino deben ser distintas"
                )
        elif self.movement_type == MovementType.INBOUND:
            if destination is None:
                raise ValueError("Una entrada (INBOUND) requiere bodega de destino")
            if source is not None:
                raise ValueError("Una entrada (INBOUND) no admite bodega de origen")
        elif self.movement_type == MovementType.OUTBOUND:
            if source is None:
                raise ValueError("Una salida (OUTBOUND) requiere bodega de origen")
            if destination is not None:
                raise ValueError("Una salida (OUTBOUND) no admite bodega de destino")
        else:  # ADJUSTMENT
            if (source is None) == (destination is None):
                raise ValueError(
                    "Un ajuste (ADJUSTMENT) requiere exactamente una bodega, "
                    "de origen o de destino"
                )
        return self


class StockMovementCreate(StockMovementBase):
    """Datos requeridos para registrar un movimiento de inventario."""


class StockMovementResponse(StockMovementBase):
    """Representación de salida de un movimiento de inventario."""

    model_config = ConfigDict(
        str_strip_whitespace=True, extra="forbid", from_attributes=True
    )

    id: int
    created_at: datetime


class StockResponse(BaseModel):
    """Representación de salida del saldo de un producto en un almacén."""

    model_config = ConfigDict(
        str_strip_whitespace=True, extra="forbid", from_attributes=True
    )

    id: int
    product_id: int
    warehouse_id: int
    quantity: int = Field(description="Cantidad actual disponible.")
    updated_at: datetime
