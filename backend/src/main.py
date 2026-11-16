"""Punto de entrada de la API del ERP modular (FastAPI).

Registra los routers de cada módulo de negocio. Por ahora solo se expone el
módulo de inventario bajo el prefijo ``/api/v1/inventory``, conforme a
``specs/inventory_spec.md`` (sección 4).

Al arrancar se ejecuta el seeding idempotente del módulo ``users`` (roles y
superusuario inicial). Si las migraciones aún no se aplicaron, el hook lo
omite y deja constancia en el log.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.modules.inventory.router import (
    inventory_exception_handler,
    router as inventory_router,
)
from src.modules.inventory.services import InventoryError
from src.modules.users.seeding import seed_users_on_startup


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Ejecuta tareas de inicialización antes de aceptar peticiones."""
    seed_users_on_startup()
    yield


app = FastAPI(
    title="SynapsisX ERP API",
    version="0.1.0",
    description="API del ERP modular construido con FastAPI y SQLAlchemy.",
    lifespan=lifespan,
)

# El frontend se sirve en otro origen (Vite :5173), por lo que el navegador
# exige CORS: sin esto las peticiones desde React fallan con "Failed to fetch".
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Traduce las excepciones de dominio de inventario a respuestas HTTP.
app.add_exception_handler(InventoryError, inventory_exception_handler)

app.include_router(inventory_router, prefix="/api/v1/inventory")
