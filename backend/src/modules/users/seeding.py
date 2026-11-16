"""Seeding idempotente del módulo ``users``.

Sincroniza el catálogo maestro de roles y garantiza la existencia de un
usuario ``ADMINISTRATOR`` inicial, conforme a ``specs/users_spec.md``
(secciones 3.2 y 7).

El proceso es idempotente:

* los roles que faltan se crean y los existentes se actualizan si su
  descripción o su lista de módulos difiere de la definición canónica;
* el superusuario solo se crea si no existe una cuenta con su correo o nombre
  de usuario.

Se puede invocar de tres formas:

* al arrancar la API (``src.main``), si las tablas ya existen;
* desde código con ``seed_users_module()``;
* manualmente con ``python -m src.modules.users.seeding``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import inspect, or_, select, text
from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.database import SessionLocal, engine
from src.core.security import hash_password
from src.modules.users.models import Role, RoleEnum, User

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RoleSeed:
    """Definición canónica de un rol y sus módulos permitidos."""

    name: RoleEnum
    description: str
    allowed_modules: tuple[str, ...]


#: Catálogo canónico de los siete roles del ERP (sección 3.1).
ROLE_SEEDS: tuple[RoleSeed, ...] = (
    RoleSeed(
        RoleEnum.ADMINISTRATOR,
        "Acceso total a todos los módulos y gestión de usuarios.",
        (
            "users",
            "inventory",
            "sales",
            "purchasing",
            "accounting",
            "hr",
            "manufacturing",
        ),
    ),
    RoleSeed(
        RoleEnum.INVENTORY,
        "Acceso exclusivo al módulo de inventario y consulta de catálogo.",
        ("inventory",),
    ),
    RoleSeed(
        RoleEnum.SALES,
        "Acceso al módulo de ventas y lectura de stock en inventario.",
        ("sales", "inventory:read"),
    ),
    RoleSeed(
        RoleEnum.PURCHASING,
        "Acceso al módulo de compras y lectura de productos/proveedores.",
        ("purchasing", "inventory:read"),
    ),
    RoleSeed(
        RoleEnum.ACCOUNTING,
        "Acceso al módulo de contabilidad y lectura de facturación/compras.",
        ("accounting", "sales:read", "purchasing:read"),
    ),
    RoleSeed(
        RoleEnum.HR,
        "Acceso exclusivo al módulo de recursos humanos.",
        ("hr",),
    ),
    RoleSeed(
        RoleEnum.MANUFACTURING,
        "Acceso al módulo de manufactura y consulta de materias primas.",
        ("manufacturing", "inventory:read"),
    ),
)


@dataclass(frozen=True)
class SeedReport:
    """Resultado de una ejecución del seeding (útil en pruebas y logs)."""

    roles_created: tuple[RoleEnum, ...] = field(default_factory=tuple)
    roles_updated: tuple[RoleEnum, ...] = field(default_factory=tuple)
    superuser_created: bool = False


def _sync_roles(db: Session) -> tuple[list[RoleEnum], list[RoleEnum]]:
    """Crea los roles ausentes y sincroniza los existentes con el catálogo."""
    existing = {role.name: role for role in db.scalars(select(Role)).all()}
    created: list[RoleEnum] = []
    updated: list[RoleEnum] = []

    for seed in ROLE_SEEDS:
        role = existing.get(seed.name)
        modules = list(seed.allowed_modules)

        if role is None:
            db.add(
                Role(
                    name=seed.name,
                    description=seed.description,
                    allowed_modules=modules,
                )
            )
            created.append(seed.name)
            continue

        if role.description != seed.description or role.allowed_modules != modules:
            role.description = seed.description
            role.allowed_modules = modules
            updated.append(seed.name)

    db.flush()
    return created, updated


def _ensure_superuser(db: Session) -> bool:
    """Crea el usuario administrador inicial si no existe (idempotente)."""
    email = str(settings.FIRST_SUPERUSER_EMAIL).strip().lower()
    username = settings.FIRST_SUPERUSER_USERNAME.strip()
    password = settings.FIRST_SUPERUSER_PASSWORD

    if not email or not username or not password:
        logger.warning(
            "Seeding del superusuario omitido: FIRST_SUPERUSER_EMAIL, "
            "FIRST_SUPERUSER_USERNAME y FIRST_SUPERUSER_PASSWORD son obligatorios."
        )
        return False

    existing = db.scalar(
        select(User).where(or_(User.email == email, User.username == username))
    )
    if existing is not None:
        logger.info(
            "Superusuario ya existente (%s); no se modifica.", existing.email
        )
        return False

    administrator = db.scalar(
        select(Role).where(Role.name == RoleEnum.ADMINISTRATOR)
    )
    if administrator is None:
        raise RuntimeError(
            "No existe el rol 'administrator'; el catálogo de roles no se aplicó."
        )

    db.add(
        User(
            email=email,
            username=username,
            full_name=settings.FIRST_SUPERUSER_FULL_NAME,
            hashed_password=hash_password(password),
            role_id=administrator.id,
            is_active=True,
        )
    )
    db.flush()
    return True


def _acquire_seed_lock(db: Session) -> None:
    """Serializa el seeding entre varios workers de uvicorn.

    En PostgreSQL se toma un *advisory lock* de transacción: se libera solo al
    hacer ``COMMIT``/``ROLLBACK``. SQLite (pruebas) no lo necesita.
    """
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext('synapsisx_erp.users.seed'))")
        )


def seed_users_module(db: Session | None = None) -> SeedReport:
    """Sincroniza roles y superusuario en una única transacción.

    Args:
        db: sesión existente (por ejemplo, en pruebas). Si se omite se abre
            una sesión nueva a partir de ``SessionLocal`` y se cierra al
            finalizar.
    """
    owns_session = db is None
    session = db if db is not None else SessionLocal()

    try:
        _acquire_seed_lock(session)
        roles_created, roles_updated = _sync_roles(session)
        superuser_created = _ensure_superuser(session)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        if owns_session:
            session.close()

    report = SeedReport(
        roles_created=tuple(roles_created),
        roles_updated=tuple(roles_updated),
        superuser_created=superuser_created,
    )
    logger.info(
        "Seeding users completado: %d rol(es) creado(s), %d actualizado(s), "
        "superusuario %s.",
        len(report.roles_created),
        len(report.roles_updated),
        "creado" if report.superuser_created else "sin cambios",
    )
    return report


def users_tables_ready() -> bool:
    """Indica si las tablas del módulo existen en la base configurada."""
    inspector = inspect(engine)
    return inspector.has_table(Role.__tablename__) and inspector.has_table(
        User.__tablename__
    )


def seed_users_on_startup() -> None:
    """Hook de arranque: omite el seeding si las migraciones no se aplicaron."""
    if not settings.AUTO_SEED_USERS:
        logger.info("Seeding de users deshabilitado (AUTO_SEED_USERS=false).")
        return

    if not users_tables_ready():
        logger.warning(
            "Seeding de users omitido: faltan las tablas 'roles'/'users'. "
            "Ejecuta 'alembic upgrade head'."
        )
        return

    seed_users_module()


if __name__ == "__main__":  # pragma: no cover - utilidad de línea de comandos
    logging.basicConfig(level=logging.INFO)
    seed_users_module()
