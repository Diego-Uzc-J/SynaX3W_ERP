"""Capa de persistencia transversal del ERP (SQLAlchemy 2.x).

Expone la clase declarativa ``Base`` que heredan todos los modelos de los
módulos, el ``engine`` y la fábrica de sesiones, además de la dependencia
``get_db`` para los endpoints de FastAPI.

La URL de conexión se toma de la variable de entorno ``DATABASE_URL``; si no
está definida se usa el valor por defecto alineado con ``docker-compose.yml``.
"""

from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DEFAULT_DATABASE_URL = "postgresql://erp_user:erp_password@localhost:5432/erp_database"


def _normalize_database_url(url: str) -> str:
    """Adapta URLs heredadas al driver ``psycopg`` (v3).

    ``docker-compose.yml`` define ``postgresql://...``; SQLAlchemy resolvería
    ese esquema hacia ``psycopg2``. Al reescribirlo a ``postgresql+psycopg``
    se usa el driver moderno sin tocar la configuración de infraestructura.
    """
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


DATABASE_URL = _normalize_database_url(
    os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
)

SQLALCHEMY_ECHO = os.getenv("SQLALCHEMY_ECHO", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

engine: Engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    echo=SQLALCHEMY_ECHO,
)

SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Clase declarativa base para todos los modelos del ERP."""


def get_db() -> Generator[Session, None, None]:
    """Dependencia de FastAPI que entrega una sesión y la cierra al finalizar."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
