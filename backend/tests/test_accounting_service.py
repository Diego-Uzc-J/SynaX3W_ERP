"""Pruebas de servicios del módulo ``accounting`` (Hito 3).

Cubren el Plan de Cuentas, la creación de borradores, la publicación con
partida doble exacta, los rechazos con rollback limpio (desequilibrio y cuenta
inactiva), la inmutabilidad de ``POSTED`` y la reversión trazable. Todo usa
SQLite en memoria, igual que el resto de la suite.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite://")

from src.core.database import Base  # noqa: E402
from src.modules.accounting.models import (  # noqa: E402
    Account,
    AccountType,
    AccountingPeriod,
    JournalEntry,
    JournalEntryStatus,
    JournalItem,
)
from src.modules.accounting.schemas import (  # noqa: E402
    AccountCreate,
    AccountUpdate,
    JournalEntryCreate,
    JournalItemCreate,
)
from src.modules.accounting.service import (  # noqa: E402
    AccountInUseError,
    ClosedAccountingPeriodError,
    DuplicateResourceError,
    ImmutableJournalEntryError,
    InactiveAccountError,
    InvalidJournalEntryError,
    InvalidJournalEntryStateError,
    ParentCycleError,
    ResourceNotFoundError,
    UnbalancedJournalEntryError,
    build_journal_entry_post_response,
    create_account,
    create_journal_entry,
    deactivate_account,
    delete_account,
    delete_journal_entry,
    get_account,
    get_journal_entry,
    list_accounts,
    post_journal_entry,
    reverse_journal_entry,
    update_account,
    update_journal_entry,
    void_journal_entry,
)

_TODAY = date(2026, 11, 19)


@pytest.fixture()
def db_session() -> Session:
    """Sesión SQLite aislada con el esquema completo del ERP."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def cash(db_session: Session) -> Account:
    """Cuenta de activo usada al debe."""
    return create_account(
        db_session,
        AccountCreate(
            code="110505", name="Caja General", account_type=AccountType.ASSET
        ),
    )


@pytest.fixture()
def revenue(db_session: Session) -> Account:
    """Cuenta de ingresos usada al haber."""
    return create_account(
        db_session,
        AccountCreate(code="4135", name="Ventas", account_type=AccountType.REVENUE),
    )


def entry_payload(
    cash_id: int,
    revenue_id: int,
    *,
    code: str = "ASI-2026-0001",
    debit: str = "500.00",
    credit: str = "500.00",
    entry_date: date = _TODAY,
    **overrides: Any,
) -> JournalEntryCreate:
    """Borrador equilibrado por defecto con una línea al debe y otra al haber."""
    values: dict[str, Any] = {
        "code": code,
        "entry_date": entry_date,
        "description": "Venta al contado",
        "reference_document": "FAC-2026-0001",
        "created_by": "admin",
        "items": [
            JournalItemCreate(account_id=cash_id, debit=Decimal(debit)),
            JournalItemCreate(account_id=revenue_id, credit=Decimal(credit)),
        ],
    }
    values.update(overrides)
    return JournalEntryCreate(**values)


def _count(db: Session, model: Any) -> int:
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


# --------------------------------------------------------------------------- #
# Plan de cuentas
# --------------------------------------------------------------------------- #


def test_create_list_update_and_deactivate_accounts(db_session: Session) -> None:
    account = create_account(
        db_session,
        AccountCreate(
            code="110505",
            name="Caja General",
            account_type=AccountType.ASSET,
        ),
    )
    assert account.code == "110505"
    assert account.is_active is True

    with pytest.raises(DuplicateResourceError):
        create_account(
            db_session,
            AccountCreate(
                code="110505", name="Otra caja", account_type=AccountType.ASSET
            ),
        )

    assert [item.id for item in list_accounts(db_session, account_type=AccountType.ASSET)] == [
        account.id
    ]
    assert list_accounts(db_session, code="4135") == []
    assert list_accounts(db_session, name="caja")[0].id == account.id
    assert list_accounts(db_session, is_active=False) == []

    updated = update_account(
        db_session,
        account.id,
        AccountUpdate(name="Caja Principal", is_active=False),
    )
    assert updated.name == "Caja Principal"
    assert updated.is_active is False
    assert list_accounts(db_session, is_active=False)[0].id == account.id

    # La desactivación es idempotente y preserva la fila.
    deactivate_account(db_session, account.id)
    assert get_account(db_session, account.id).is_active is False


def test_update_account_rejects_cycles(db_session: Session, cash: Account) -> None:
    child = create_account(
        db_session,
        AccountCreate(
            code="110510",
            name="Caja Menor",
            account_type=AccountType.ASSET,
            parent_id=cash.id,
        ),
    )
    with pytest.raises(ParentCycleError):
        update_account(db_session, cash.id, AccountUpdate(parent_id=child.id))
    with pytest.raises(ParentCycleError):
        update_account(db_session, cash.id, AccountUpdate(parent_id=cash.id))


def test_delete_account_blocked_by_children_and_movements(
    db_session: Session, cash: Account, revenue: Account
) -> None:
    empty = create_account(
        db_session,
        AccountCreate(code="5100", name="Gastos", account_type=AccountType.EXPENSE),
    )
    delete_account(db_session, empty.id)
    with pytest.raises(ResourceNotFoundError):
        get_account(db_session, empty.id)

    create_account(
        db_session,
        AccountCreate(
            code="110510",
            name="Caja Menor",
            account_type=AccountType.ASSET,
            parent_id=cash.id,
        ),
    )
    with pytest.raises(AccountInUseError):
        delete_account(db_session, cash.id)

    entry = create_journal_entry(db_session, entry_payload(cash.id, revenue.id))
    with pytest.raises(AccountInUseError):
        delete_account(db_session, revenue.id)

    # Defensa en profundidad: el borrado directo por ORM también se bloquea.
    db_session.delete(revenue)
    with pytest.raises(AccountInUseError):
        db_session.commit()
    db_session.rollback()
    assert _count(db_session, JournalEntry) == 1


# --------------------------------------------------------------------------- #
# Creación de asientos
# --------------------------------------------------------------------------- #


def test_create_entry_validates_code_and_accounts(
    db_session: Session, cash: Account, revenue: Account
) -> None:
    entry = create_journal_entry(db_session, entry_payload(cash.id, revenue.id))
    assert entry.status is JournalEntryStatus.DRAFT
    assert len(entry.items) == 2

    with pytest.raises(DuplicateResourceError):
        create_journal_entry(db_session, entry_payload(cash.id, revenue.id))

    with pytest.raises(ResourceNotFoundError):
        create_journal_entry(
            db_session, entry_payload(cash.id, 9999, code="ASI-2026-0002")
        )

    deactivate_account(db_session, revenue.id)
    with pytest.raises(InactiveAccountError):
        create_journal_entry(
            db_session, entry_payload(cash.id, revenue.id, code="ASI-2026-0002")
        )
    assert _count(db_session, JournalEntry) == 1
    assert _count(db_session, JournalItem) == 2

    # La service revalida importes aunque el esquema ya los haya validado.
    update_account(db_session, revenue.id, AccountUpdate(is_active=True))
    forged = JournalItemCreate.model_construct(
        account_id=cash.id, debit=Decimal("-1.00"), credit=Decimal("0.00")
    )
    with pytest.raises(InvalidJournalEntryError):
        create_journal_entry(
            db_session,
            entry_payload(
                cash.id,
                revenue.id,
                code="ASI-2026-0003",
                items=[forged, JournalItemCreate(account_id=revenue.id, credit=Decimal("1.00"))],
            ),
        )


# --------------------------------------------------------------------------- #
# Publicación, rollback e inmutabilidad
# --------------------------------------------------------------------------- #


def test_post_balanced_entry(
    db_session: Session, cash: Account, revenue: Account
) -> None:
    entry = create_journal_entry(db_session, entry_payload(cash.id, revenue.id))
    posted = post_journal_entry(db_session, entry.id)
    assert posted.status is JournalEntryStatus.POSTED
    assert posted.posted_at is not None

    response = build_journal_entry_post_response(posted)
    assert response.total_debit == Decimal("500.00")
    assert response.total_credit == Decimal("500.00")

    with pytest.raises(ImmutableJournalEntryError):
        post_journal_entry(db_session, entry.id)


def test_post_unbalanced_entry_rolls_back_without_partial_rows(
    db_session: Session, cash: Account, revenue: Account
) -> None:
    entry = create_journal_entry(
        db_session,
        entry_payload(cash.id, revenue.id, debit="500.00", credit="450.00"),
    )
    with pytest.raises(UnbalancedJournalEntryError) as exc:
        post_journal_entry(db_session, entry.id)

    assert "no está sumariamente equilibrado" in str(exc.value)
    draft = get_journal_entry(db_session, entry.id)
    assert draft.status is JournalEntryStatus.DRAFT
    assert draft.posted_at is None
    assert [item.debit for item in draft.items] == [Decimal("500.00"), Decimal("0.00")]
    assert [item.credit for item in draft.items] == [Decimal("0.00"), Decimal("450.00")]
    assert _count(db_session, JournalEntry) == 1
    assert _count(db_session, JournalItem) == 2


def test_post_with_inactive_account_rolls_back(
    db_session: Session, cash: Account, revenue: Account
) -> None:
    entry = create_journal_entry(db_session, entry_payload(cash.id, revenue.id))
    deactivate_account(db_session, revenue.id)

    with pytest.raises(InactiveAccountError):
        post_journal_entry(db_session, entry.id)

    draft = get_journal_entry(db_session, entry.id)
    assert draft.status is JournalEntryStatus.DRAFT
    assert draft.posted_at is None
    assert _count(db_session, JournalItem) == 2


def test_post_in_closed_period_is_rejected(
    db_session: Session, cash: Account, revenue: Account
) -> None:
    db_session.add(
        AccountingPeriod(
            name="2026-11",
            start_date=date(2026, 11, 1),
            end_date=date(2026, 11, 30),
            is_closed=True,
        )
    )
    db_session.commit()
    entry = create_journal_entry(db_session, entry_payload(cash.id, revenue.id))

    with pytest.raises(ClosedAccountingPeriodError):
        post_journal_entry(db_session, entry.id)
    assert get_journal_entry(db_session, entry.id).status is JournalEntryStatus.DRAFT


def test_posted_entry_cannot_be_edited_or_deleted(
    db_session: Session, cash: Account, revenue: Account
) -> None:
    entry = create_journal_entry(db_session, entry_payload(cash.id, revenue.id))
    post_journal_entry(db_session, entry.id)

    replacement = entry_payload(
        cash.id, revenue.id, code="ASI-2026-0001", debit="600.00", credit="600.00"
    )
    with pytest.raises(ImmutableJournalEntryError):
        update_journal_entry(db_session, entry.id, replacement)
    with pytest.raises(ImmutableJournalEntryError):
        delete_journal_entry(db_session, entry.id)

    entry.description = "Intento de cambio directo"
    with pytest.raises(ImmutableJournalEntryError):
        db_session.commit()
    db_session.rollback()

    db_session.delete(entry)
    with pytest.raises(ImmutableJournalEntryError):
        db_session.commit()
    db_session.rollback()
    assert get_journal_entry(db_session, entry.id).status is JournalEntryStatus.POSTED


def test_draft_can_be_updated_voided_and_deleted(
    db_session: Session, cash: Account, revenue: Account
) -> None:
    entry = create_journal_entry(db_session, entry_payload(cash.id, revenue.id))
    updated = update_journal_entry(
        db_session,
        entry.id,
        entry_payload(
            cash.id,
            revenue.id,
            code="ASI-2026-0999",
            description="Borrador corregido",
            debit="700.00",
            credit="700.00",
        ),
    )
    assert updated.code == "ASI-2026-0999"
    assert updated.items[0].debit == Decimal("700.00")

    voided = void_journal_entry(db_session, entry.id)
    assert voided.status is JournalEntryStatus.VOID
    with pytest.raises(InvalidJournalEntryStateError):
        post_journal_entry(db_session, entry.id)
    with pytest.raises(InvalidJournalEntryStateError):
        void_journal_entry(db_session, entry.id)

    discard = create_journal_entry(
        db_session, entry_payload(cash.id, revenue.id, code="ASI-2026-1000")
    )
    delete_journal_entry(db_session, discard.id)
    with pytest.raises(ResourceNotFoundError):
        get_journal_entry(db_session, discard.id)


# --------------------------------------------------------------------------- #
# Reversión trazable
# --------------------------------------------------------------------------- #


def test_reverse_posted_entry_creates_traceable_compensating_entry(
    db_session: Session, cash: Account, revenue: Account
) -> None:
    original = create_journal_entry(db_session, entry_payload(cash.id, revenue.id))
    post_journal_entry(db_session, original.id)

    reversal = reverse_journal_entry(db_session, original.id, created_by="admin")
    assert reversal.code.startswith(f"REV-{date.today().year}-")
    assert reversal.status is JournalEntryStatus.POSTED
    assert reversal.posted_at is not None
    assert reversal.reference_document == original.code
    assert [item.debit for item in reversal.items] == [
        Decimal("0.00"),
        Decimal("500.00"),
    ]
    assert [item.credit for item in reversal.items] == [
        Decimal("500.00"),
        Decimal("0.00"),
    ]

    unchanged = get_journal_entry(db_session, original.id)
    assert unchanged.status is JournalEntryStatus.POSTED
    assert unchanged.description == "Venta al contado"
    assert _count(db_session, JournalEntry) == 2

    draft = create_journal_entry(
        db_session, entry_payload(cash.id, revenue.id, code="ASI-2026-1001")
    )
    with pytest.raises(InvalidJournalEntryStateError):
        reverse_journal_entry(db_session, draft.id)
