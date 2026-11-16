"""Capa de persistencia transversal del ERP (SQLAlchemy 2.x).

Expone la clase declarativa ``Base`` que heredan todos los modelos de los
módulos, el ``engine`` y la fábrica de sesiones, además de la dependencia
``get_db`` para los endpoints de FastAPI.

La URL de conexión se toma de ``src.core.config.settings`` (que lee
``DATABASE_URL``); si no está definida se usa el valor por defecto alineado con
``docker-compose.yml``.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.core.config import settings


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


DATABASE_URL = _normalize_database_url(settings.DATABASE_URL)

SQLALCHEMY_ECHO = settings.SQLALCHEMY_ECHO

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
