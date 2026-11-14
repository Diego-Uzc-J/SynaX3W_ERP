"""Punto de entrada de la API del ERP modular (FastAPI).

Registra los routers de cada módulo de negocio. Por ahora solo se expone el
módulo de inventario bajo el prefijo ``/api/v1/inventory``, conforme a
``specs/inventory_spec.md`` (sección 4).
"""

from __future__ import annotations

from fastapi import FastAPI

from src.modules.inventory.router import (
    inventory_exception_handler,
    router as inventory_router,
)
from src.modules.inventory.services import InventoryError

app = FastAPI(
    title="SynapsisX ERP API",
    version="0.1.0",
    description="API del ERP modular construido con FastAPI y SQLAlchemy.",
)

# Traduce las excepciones de dominio de inventario a respuestas HTTP.
app.add_exception_handler(InventoryError, inventory_exception_handler)

app.include_router(inventory_router, prefix="/api/v1/inventory")
