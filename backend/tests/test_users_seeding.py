"""Pruebas del Hito 1 del módulo ``users``: modelos y seeding idempotente.

Se ejecutan sobre SQLite en memoria para no depender de PostgreSQL. El
contrato verificado es el de ``specs/users_spec.md`` (sección 3) y el del
seeding de la sección 7:

* las siete entradas de ``RoleEnum`` se persisten con su valor técnico en
  minúsculas (``administrator``, ``inventory``, ...);
* el catálogo de roles y sus ``allowed_modules`` coincide con el canónico;
* el superusuario se crea una sola vez, con hash Argon2id verificable y los
  valores por defecto de bloqueo;
* una segunda ejecución no duplica filas y solo actualiza lo que difiere.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# ``backend`` debe estar en sys.path para importar el paquete ``src``.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Igual que en ``test_inventory.py``: el engine global se crea al importar.
os.environ["DATABASE_URL"] = "sqlite://"

from pwdlib import PasswordHash  # noqa: E402
from src.core.config import settings  # noqa: E402
from src.core.database import Base  # noqa: E402
from src.modules.users.models import Role, RoleEnum, User  # noqa: E402
from src.modules.users.seeding import ROLE_SEEDS, seed_users_module  # noqa: E402


@pytest.fixture()
def db_engine() -> Generator[Engine, None, None]:
    """Engine SQLite en memoria compartido por todas las sesiones de la prueba."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def db_session(db_engine: Engine) -> Generator[Session, None, None]:
    session_factory = sessionmaker(bind=db_engine, expire_on_commit=False)
    with session_factory() as session:
        yield session


def _count(session: Session, model: type[Base]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def test_seeding_creates_seven_roles_and_superuser(db_session: Session) -> None:
    report = seed_users_module(db_session)

    assert set(report.roles_created) == set(RoleEnum)
    assert report.roles_updated == ()
    assert report.superuser_created is True

    assert _count(db_session, Role) == 7
    assert _count(db_session, User) == 1

    # El enum nativo debe almacenar los valores en minúsculas.
    raw_names = db_session.execute(text("SELECT name FROM roles")).scalars().all()
    assert set(raw_names) == {seed.name.value for seed in ROLE_SEEDS}

    sales = db_session.scalar(select(Role).where(Role.name == RoleEnum.SALES))
    assert sales is not None
    assert sales.allowed_modules == ["sales", "inventory:read"]

    admin = db_session.scalar(select(User))
    assert admin is not None
    assert admin.email == str(settings.FIRST_SUPERUSER_EMAIL).lower()
    assert admin.username == settings.FIRST_SUPERUSER_USERNAME
    assert admin.role.name is RoleEnum.ADMINISTRATOR
    assert admin.is_active is True
    assert admin.failed_login_attempts == 0
    assert admin.locked_until is None
    assert PasswordHash.recommended().verify(
        settings.FIRST_SUPERUSER_PASSWORD, admin.hashed_password
    )


def test_seeding_is_idempotent(db_session: Session) -> None:
    seed_users_module(db_session)

    second = seed_users_module(db_session)

    assert second.roles_created == ()
    assert second.roles_updated == ()
    assert second.superuser_created is False
    assert _count(db_session, Role) == 7
    assert _count(db_session, User) == 1


def test_seeding_synchronizes_changed_roles(db_session: Session) -> None:
    seed_users_module(db_session)

    sales = db_session.scalar(select(Role).where(Role.name == RoleEnum.SALES))
    assert sales is not None
    sales.allowed_modules = ["stale"]
    db_session.commit()

    report = seed_users_module(db_session)

    assert report.roles_created == ()
    assert report.roles_updated == (RoleEnum.SALES,)
    assert report.superuser_created is False
    db_session.refresh(sales)
    assert sales.allowed_modules == ["sales", "inventory:read"]
    assert _count(db_session, User) == 1


def test_user_email_is_normalized_to_lowercase(db_session: Session) -> None:
    seed_users_module(db_session)
    administrator = db_session.scalar(
        select(Role).where(Role.name == RoleEnum.ADMINISTRATOR)
    )
    assert administrator is not None

    user = User(
        email="  Mixed.Case@Example.COM ",
        username="  mixed_user  ",
        full_name="Usuario de Prueba",
        hashed_password="no-usado",
        role_id=administrator.id,
    )
    db_session.add(user)
    db_session.flush()

    assert user.email == "mixed.case@example.com"
    assert user.username == "mixed_user"
