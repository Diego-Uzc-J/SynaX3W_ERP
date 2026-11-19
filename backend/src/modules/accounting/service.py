"""Servicios de dominio del módulo de Finanzas y Contabilidad.

Implementa el Hito 3 de ``specs/accounting_spec.md`` para el Plan de Cuentas y
el libro diario:

* **Cuentas:** alta con ``code`` único, listado filtrable, actualización parcial,
  desactivación (borrado lógico) y bloqueo de borrado físico cuando la cuenta
  tiene movimientos o subcuentas (regla 8).
* **Asientos en borrador:** unicidad de ``code``, existencia y ``is_active`` de
  todas las cuentas referenciadas (regla 4) y líneas no negativas de un solo
  lado (regla 6).
* **Contabilización:** ``post_journal_entry`` comprueba la partida doble exacta,
  cuentas activas y periodo abierto, y escribe estado, ``posted_at`` y líneas en
  un único ``COMMIT`` (reglas 1, 5 y 7).
* **Inmutabilidad y contrapartidas:** los asientos ``POSTED`` no se editan ni se
  borran; los borradores pueden anularse (``VOID``) y los publicados se corrigen
  con un asiento de reversión trazable (regla 2).

Toda operación de escritura usa :func:`_atomic`, que confirma al finalizar y
hace ``rollback`` ante cualquier excepción, de modo que un asiento desbalanceado
o con una cuenta inactiva no deja registros parciales. Las excepciones derivan
de ``fastapi.HTTPException`` con ``status_code`` 400/404/409, igual que en
``sales`` y ``purchasing``.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import event, func, inspect, select
from sqlalchemy.orm import Session, selectinload

from src.modules.accounting.models import (
    Account,
    AccountingPeriod,
    JournalEntry,
    JournalEntryStatus,
    JournalItem,
)
from src.modules.accounting.schemas import (
    AccountCreate,
    AccountUpdate,
    JournalEntryCreate,
    JournalEntryPostResponse,
    JournalItemCreate,
)

__all__ = [
    "AccountInUseError",
    "AccountingServiceError",
    "ClosedAccountingPeriodError",
    "DuplicateResourceError",
    "ImmutableJournalEntryError",
    "InactiveAccountError",
    "InvalidJournalEntryError",
    "InvalidJournalEntryStateError",
    "ParentCycleError",
    "ResourceNotFoundError",
    "UnbalancedJournalEntryError",
    "build_journal_entry_post_response",
    "create_account",
    "create_journal_entry",
    "deactivate_account",
    "delete_account",
    "delete_journal_entry",
    "ensure_account_active",
    "get_account",
    "get_journal_entry",
    "list_accounts",
    "list_journal_entries",
    "post_journal_entry",
    "reverse_journal_entry",
    "reject_journal_entry_mutation",
    "update_account",
    "update_journal_entry",
    "void_journal_entry",
]

#: Unidad mínima de los importes monetarios del ERP.
_CENT = Decimal("0.01")

#: Límite de ``Numeric(14, 2)`` expresado como Decimal.
_MAX_MONEY = Decimal("999999999999.99")

#: Clave base del advisory lock que serializa la secuencia ``REV-YYYY-XXXX``.
_REVERSAL_CODE_LOCK_BASE = 8_400_000

#: Transiciones permitidas desde un borrador.
_DRAFT_TRANSITIONS = frozenset(
    {JournalEntryStatus.POSTED, JournalEntryStatus.VOID}
)


# --------------------------------------------------------------------------- #
# Excepciones HTTP de dominio
# --------------------------------------------------------------------------- #


class AccountingServiceError(HTTPException):
    """Error base del módulo de contabilidad con su equivalencia HTTP."""

    status_code: int = 400

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=self.status_code, detail=detail)

    def __str__(self) -> str:
        """Devuelve solo el mensaje, como las excepciones de dominio del ERP."""
        return str(self.detail)


class ResourceNotFoundError(AccountingServiceError):
    """El recurso solicitado no existe."""

    status_code = 404


class DuplicateResourceError(AccountingServiceError):
    """Se intentó persistir un valor que debe ser único."""

    status_code = 409


class InactiveAccountError(AccountingServiceError):
    """Una línea afecta una cuenta desactivada (regla 4 de la spec)."""

    status_code = 400


class AccountInUseError(AccountingServiceError):
    """La cuenta tiene movimientos o subcuentas y solo puede desactivarse."""

    status_code = 409


class ParentCycleError(AccountingServiceError):
    """La cuenta padre propuesta generaría un ciclo en la jerarquía."""

    status_code = 400


class InvalidJournalEntryError(AccountingServiceError):
    """El comprobante no cumple una regla de líneas o de periodo."""

    status_code = 400


class UnbalancedJournalEntryError(InvalidJournalEntryError):
    """Los débitos y los créditos no coinciden (regla 1 de la spec)."""

    status_code = 400

    def __init__(self, total_debit: Decimal, total_credit: Decimal) -> None:
        self.total_debit = total_debit
        self.total_credit = total_credit
        super().__init__(
            "El comprobante no está sumariamente equilibrado: "
            f"débitos {total_debit} != créditos {total_credit}"
        )


class ClosedAccountingPeriodError(InvalidJournalEntryError):
    """La fecha del asiento pertenece a un periodo contable cerrado."""

    status_code = 400

    def __init__(self, entry_date: date) -> None:
        self.entry_date = entry_date
        super().__init__(
            f"No se puede contabilizar el {entry_date.isoformat()}: "
            "el periodo contable está cerrado"
        )


class InvalidJournalEntryStateError(AccountingServiceError):
    """La operación no es válida para el estado actual del asiento."""

    status_code = 409


class ImmutableJournalEntryError(AccountingServiceError):
    """Un asiento publicado no puede modificarse ni eliminarse (regla 2)."""

    status_code = 400


# --------------------------------------------------------------------------- #
# Utilidades internas y control transaccional
# --------------------------------------------------------------------------- #


@contextmanager
def _atomic(db: Session) -> Iterator[None]:
    """Confirma la unidad de trabajo o revierte cualquier cambio ante un error."""
    try:
        yield
        db.commit()
    except Exception:
        db.rollback()
        raise


def _as_decimal(value: Any) -> Decimal:
    """Convierte valores de SQLAlchemy/SQLite a ``Decimal`` sin perder escala."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _money(value: Any) -> Decimal:
    """Redondea a dos decimales con ``ROUND_HALF_UP``."""
    return _as_decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP)


def _ensure_money_range(value: Decimal, *, label: str) -> None:
    """Valida que un importe quepa en ``Numeric(14, 2)``."""
    if value.copy_abs() > _MAX_MONEY:
        raise InvalidJournalEntryError(
            f"El {label} excede el máximo permitido (14,2): {value}"
        )


def _as_status(value: Any) -> JournalEntryStatus | Any:
    """Normaliza el valor leído de la BD a ``JournalEntryStatus``."""
    if isinstance(value, JournalEntryStatus):
        return value
    try:
        return JournalEntryStatus(value)
    except (TypeError, ValueError):
        return value


def _get_account(db: Session, account_id: int) -> Account:
    """Obtiene una cuenta por id, sin importar su estado."""
    account = db.get(Account, account_id)
    if account is None:
        raise ResourceNotFoundError(f"Cuenta contable {account_id} no encontrada")
    return account


def ensure_account_active(db: Session, account_id: int) -> Account:
    """Obtiene una cuenta y exige que esté activa para recibir movimientos."""
    account = _get_account(db, account_id)
    if not account.is_active:
        raise InactiveAccountError(
            f"La cuenta {account.code} ('{account.name}') está inactiva y "
            "no admite movimientos contables"
        )
    return account


def _ensure_unique_account_code(
    db: Session, code: str, *, exclude_id: int | None = None
) -> None:
    """Verifica que el código del PUC no pertenezca a otra cuenta."""
    stmt = select(Account.id).where(Account.code == code)
    if exclude_id is not None:
        stmt = stmt.where(Account.id != exclude_id)
    if db.execute(stmt.limit(1)).first() is not None:
        raise DuplicateResourceError(
            f"Ya existe una cuenta contable con el código '{code}'"
        )


def _ensure_unique_entry_code(db: Session, code: str) -> None:
    """Verifica que el código del comprobante no esté en uso (regla 6)."""
    if db.execute(
        select(JournalEntry.id).where(JournalEntry.code == code).limit(1)
    ).first() is not None:
        raise DuplicateResourceError(
            f"Ya existe un asiento contable con el código '{code}'"
        )


def _ensure_no_parent_cycle(db: Session, account_id: int, parent_id: int) -> None:
    """Rechaza padres iguales a la cuenta o descendientes de ella."""
    current = parent_id
    seen: set[int] = set()
    while current is not None and current not in seen:
        if current == account_id:
            raise ParentCycleError(
                "La cuenta padre no puede ser la propia cuenta ni una subcuenta"
            )
        seen.add(current)
        parent = db.get(Account, current)
        if parent is None:
            raise ResourceNotFoundError(
                f"Cuenta padre {current} no encontrada"
            )
        current = parent.parent_id


def _ensure_account_deletable(db: Session, account_id: int) -> None:
    """Bloquea el borrado físico si hay movimientos o subcuentas (regla 8)."""
    has_children = db.execute(
        select(Account.id).where(Account.parent_id == account_id).limit(1)
    ).first()
    if has_children is not None:
        raise AccountInUseError(
            "La cuenta tiene subcuentas; desactívela en lugar de eliminarla"
        )

    has_items = db.execute(
        select(JournalItem.id).where(JournalItem.account_id == account_id).limit(1)
    ).first()
    if has_items is not None:
        raise AccountInUseError(
            "La cuenta tiene movimientos contables; desactívela en lugar de "
            "eliminarla"
        )


def _ensure_accounts_available(
    db: Session, account_ids: Sequence[int]
) -> dict[int, Account]:
    """Devuelve las cuentas referenciadas, exigiendo que existan y estén activas."""
    unique_ids = set(account_ids)
    accounts = {
        account.id: account
        for account in db.scalars(
            select(Account).where(Account.id.in_(list(unique_ids)))
        ).all()
    }
    missing = unique_ids - accounts.keys()
    if missing:
        raise ResourceNotFoundError(
            "Cuentas contables no encontradas: "
            + ", ".join(str(value) for value in sorted(missing))
        )
    inactive = [account for account in accounts.values() if not account.is_active]
    if inactive:
        raise InactiveAccountError(
            "No se permiten movimientos sobre cuentas contables inactivas: "
            + ", ".join(sorted(account.code for account in inactive))
        )
    return accounts


def _build_items(db: Session, data: Sequence[JournalItemCreate]) -> list[JournalItem]:
    """Construye líneas validando importes y cuentas activas."""
    if len(data) < 2:
        raise InvalidJournalEntryError(
            "Un asiento contable debe tener al menos dos líneas"
        )

    _ensure_accounts_available(db, [item.account_id for item in data])
    items: list[JournalItem] = []
    for line in data:
        debit = _money(line.debit)
        credit = _money(line.credit)
        _ensure_money_range(debit, label="débito de la línea")
        _ensure_money_range(credit, label="crédito de la línea")
        if debit < 0 or credit < 0:
            raise InvalidJournalEntryError(
                " Los importes de débito y crédito no pueden ser negativos"
            )
        if debit > 0 and credit > 0:
            raise InvalidJournalEntryError(
                "Una línea no puede tener débito y crédito positivos simultáneamente"
            )
        items.append(
            JournalItem(
                account_id=line.account_id,
                debit=debit,
                credit=credit,
                description=line.description,
            )
        )
    return items


def _items_totals(items: Sequence[JournalItem]) -> tuple[Decimal, Decimal]:
    """Suma débitos y créditos de unas líneas con precisión decimal."""
    total_debit = Decimal("0.00")
    total_credit = Decimal("0.00")
    for item in items:
        total_debit += _money(item.debit)
        total_credit += _money(item.credit)
    return _money(total_debit), _money(total_credit)


def _entry_totals(entry: JournalEntry) -> tuple[Decimal, Decimal]:
    """Suma débitos y créditos de las líneas de un asiento."""
    return _items_totals(entry.items)


def _ensure_balanced(entry: JournalEntry) -> tuple[Decimal, Decimal]:
    """Exige partida doble exacta y devuelve ``(débitos, créditos)``."""
    total_debit, total_credit = _entry_totals(entry)
    if total_debit != total_credit:
        raise UnbalancedJournalEntryError(total_debit, total_credit)
    return total_debit, total_credit


def _ensure_open_period(db: Session, entry_date: date) -> None:
    """Bloquea la contabilización en un periodo cerrado (regla 7).

    Si no existe un periodo que cubra la fecha se permite publicar: la spec
    solo prohíbe hacerlo en un ``AccountingPeriod`` marcado como cerrado.
    """
    closed = db.execute(
        select(AccountingPeriod.id)
        .where(
            AccountingPeriod.is_closed.is_(True),
            AccountingPeriod.start_date <= entry_date,
            AccountingPeriod.end_date >= entry_date,
        )
        .limit(1)
    ).first()
    if closed is not None:
        raise ClosedAccountingPeriodError(entry_date)


def _lock_sequence(db: Session, *, base: int, year: int) -> None:
    """Serializa la generación de códigos en PostgreSQL."""
    if db.get_bind().dialect.name == "postgresql":
        db.execute(select(func.pg_advisory_xact_lock(base + year)))


def _next_reversal_code(db: Session, year: int) -> str:
    """Devuelve el siguiente código ``REV-YYYY-XXXX`` para el año indicado."""
    _lock_sequence(db, base=_REVERSAL_CODE_LOCK_BASE, year=year)
    prefix = f"REV-{year}-"
    rows = db.scalars(
        select(JournalEntry.code).where(JournalEntry.code.like(f"{prefix}%"))
    ).all()
    max_sequence = 0
    for code in rows:
        suffix = code[len(prefix) :]
        if suffix.isdigit():
            max_sequence = max(max_sequence, int(suffix))
    return f"{prefix}{max_sequence + 1:04d}"


# --------------------------------------------------------------------------- #
# Plan de cuentas — /api/v1/accounting/accounts
# --------------------------------------------------------------------------- #


def create_account(db: Session, data: AccountCreate) -> Account:
    """Registra una cuenta validando ``code`` único y cuenta padre existente."""
    _ensure_unique_account_code(db, data.code)
    if data.parent_id is not None:
        _get_account(db, data.parent_id)

    account = Account(**data.model_dump())
    try:
        with _atomic(db):
            db.add(account)
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            raise DuplicateResourceError(
                f"Ya existe una cuenta contable con el código '{data.code}'"
            ) from exc
        raise
    db.refresh(account)
    return account


def get_account(db: Session, account_id: int) -> Account:
    """Obtiene una cuenta por id o lanza ``ResourceNotFoundError``."""
    return _get_account(db, account_id)


def list_accounts(
    db: Session,
    *,
    skip: int = 0,
    limit: int = 100,
    code: str | None = None,
    name: str | None = None,
    account_type: Any | None = None,
    is_active: bool | None = None,
    parent_id: int | None = None,
) -> list[Account]:
    """Lista cuentas con filtros por tipo, código, nombre y estado."""
    stmt = select(Account)
    if code:
        stmt = stmt.where(Account.code.ilike(f"%{code}%"))
    if name:
        stmt = stmt.where(Account.name.ilike(f"%{name}%"))
    if account_type is not None:
        stmt = stmt.where(Account.account_type == account_type)
    if is_active is not None:
        stmt = stmt.where(Account.is_active.is_(is_active))
    if parent_id is not None:
        stmt = stmt.where(Account.parent_id == parent_id)
    stmt = stmt.order_by(Account.code).offset(skip).limit(limit)
    return list(db.scalars(stmt).all())


def update_account(db: Session, account_id: int, data: AccountUpdate) -> Account:
    """Actualiza parcialmente una cuenta, impidiendo ciclos en la jerarquía."""
    account = _get_account(db, account_id)
    changes = data.model_dump(exclude_unset=True)

    new_code = changes.get("code")
    if new_code is not None and new_code != account.code:
        _ensure_unique_account_code(db, new_code, exclude_id=account_id)
    if "parent_id" in changes and changes["parent_id"] is not None:
        _ensure_no_parent_cycle(db, account_id, changes["parent_id"])

    try:
        with _atomic(db):
            for field, value in changes.items():
                setattr(account, field, value)
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            raise DuplicateResourceError(
                f"Ya existe una cuenta contable con el código '{new_code}'"
            ) from exc
        raise
    db.refresh(account)
    return account


def deactivate_account(db: Session, account_id: int) -> Account:
    """Desactiva una cuenta (borrado lógico) preservando su historial."""
    account = _get_account(db, account_id)
    if account.is_active:
        with _atomic(db):
            account.is_active = False
        db.refresh(account)
    return account


def delete_account(db: Session, account_id: int) -> None:
    """Elimina una cuenta vacía; las que tienen movimientos o hijos solo se desactivan."""
    account = _get_account(db, account_id)
    _ensure_account_deletable(db, account_id)
    with _atomic(db):
        db.delete(account)


# --------------------------------------------------------------------------- #
# Asientos contables — /api/v1/accounting/entries
# --------------------------------------------------------------------------- #


def get_journal_entry(
    db: Session, entry_id: int, *, for_update: bool = False
) -> JournalEntry:
    """Obtiene un asiento con sus líneas, opcionalmente bloqueando la fila."""
    stmt = select(JournalEntry).options(selectinload(JournalEntry.items))
    if for_update:
        stmt = stmt.with_for_update()
    entry = db.scalars(stmt.where(JournalEntry.id == entry_id)).first()
    if entry is None:
        raise ResourceNotFoundError(f"Asiento contable {entry_id} no encontrado")
    return entry


def list_journal_entries(
    db: Session,
    *,
    skip: int = 0,
    limit: int = 100,
    code: str | None = None,
    status: JournalEntryStatus | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[JournalEntry]:
    """Lista asientos con filtros por código, estado y rango de fechas."""
    stmt = select(JournalEntry).options(selectinload(JournalEntry.items))
    if code:
        stmt = stmt.where(JournalEntry.code.ilike(f"%{code}%"))
    if status is not None:
        stmt = stmt.where(JournalEntry.status == status)
    if date_from is not None:
        stmt = stmt.where(JournalEntry.entry_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(JournalEntry.entry_date <= date_to)
    stmt = stmt.order_by(JournalEntry.id).offset(skip).limit(limit)
    return list(db.scalars(stmt).all())


def create_journal_entry(db: Session, data: JournalEntryCreate) -> JournalEntry:
    """Crea un comprobante en ``DRAFT`` con líneas y cuentas válidas.

    No se exige equilibrio aquí: la spec permite borradores desequilibrados y
    la partida doble se comprueba al publicar (regla 1).
    """
    _ensure_unique_entry_code(db, data.code)
    items = _build_items(db, data.items)

    entry = JournalEntry(
        code=data.code,
        entry_date=data.entry_date,
        description=data.description,
        reference_document=data.reference_document,
        status=JournalEntryStatus.DRAFT,
        created_by=data.created_by,
        items=items,
    )
    try:
        with _atomic(db):
            db.add(entry)
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            raise DuplicateResourceError(
                f"Ya existe un asiento contable con el código '{data.code}'"
            ) from exc
        raise
    db.refresh(entry)
    return entry


def update_journal_entry(
    db: Session, entry_id: int, data: JournalEntryCreate
) -> JournalEntry:
    """Sustituye el encabezado y las líneas de un asiento que siga en ``DRAFT``."""
    entry = get_journal_entry(db, entry_id, for_update=True)
    if entry.status is not JournalEntryStatus.DRAFT:
        raise ImmutableJournalEntryError(
            f"El asiento '{entry.code}' está {entry.status.value}: los asientos "
            "publicados o anulados no se editan; use un comprobante de reversión"
        )

    if data.code != entry.code:
        _ensure_unique_entry_code(db, data.code)
    items = _build_items(db, data.items)

    with _atomic(db):
        entry.code = data.code
        entry.entry_date = data.entry_date
        entry.description = data.description
        entry.reference_document = data.reference_document
        entry.created_by = data.created_by
        entry.items.clear()
        entry.items.extend(items)
    db.refresh(entry)
    return entry


def delete_journal_entry(db: Session, entry_id: int) -> None:
    """Descarta un borrador; los asientos ``POSTED`` son inmutables."""
    entry = get_journal_entry(db, entry_id, for_update=True)
    if entry.status is JournalEntryStatus.POSTED:
        raise ImmutableJournalEntryError(
            f"El asiento '{entry.code}' está publicado y no puede eliminarse: "
            "registre un asiento de reversión"
        )
    with _atomic(db):
        db.delete(entry)


def post_journal_entry(db: Session, entry_id: int) -> JournalEntry:
    """Contabiliza un borrador en una transacción atómica (reglas 1, 4, 5 y 7).

    Si falla cualquiera de las comprobaciones, ``_atomic`` revierte la sesión:
    el asiento permanece en ``DRAFT`` con ``posted_at=None`` y no queda ningún
    cambio parcial en las líneas o en el periodo.
    """
    entry = get_journal_entry(db, entry_id, for_update=True)
    if entry.status is JournalEntryStatus.POSTED:
        raise ImmutableJournalEntryError(
            f"El asiento '{entry.code}' ya está publicado"
        )
    if entry.status is JournalEntryStatus.VOID:
        raise InvalidJournalEntryStateError(
            f"El asiento '{entry.code}' está anulado y no puede publicarse"
        )

    with _atomic(db):
        _ensure_accounts_available(db, [item.account_id for item in entry.items])
        _ensure_open_period(db, entry.entry_date)
        _ensure_balanced(entry)
        entry.status = JournalEntryStatus.POSTED
        entry.posted_at = datetime.now(timezone.utc)
    db.refresh(entry)
    return entry


def void_journal_entry(db: Session, entry_id: int) -> JournalEntry:
    """Anula un borrador; un asiento publicado exige una reversión trazable."""
    entry = get_journal_entry(db, entry_id, for_update=True)
    if entry.status is JournalEntryStatus.POSTED:
        raise ImmutableJournalEntryError(
            f"El asiento '{entry.code}' está publicado: use reverse_journal_entry "
            "para generar un comprobante de reversión"
        )
    if entry.status is JournalEntryStatus.VOID:
        raise InvalidJournalEntryStateError(
            f"El asiento '{entry.code}' ya está anulado"
        )
    with _atomic(db):
        entry.status = JournalEntryStatus.VOID
    db.refresh(entry)
    return entry


def reverse_journal_entry(
    db: Session,
    entry_id: int,
    *,
    created_by: str | None = None,
) -> JournalEntry:
    """Genera y publica un asiento de reversión de uno ``POSTED``.

    El comprobante nuevo invierte débitos y créditos, referencia el código del
    original en ``reference_document`` y nace en ``POSTED`` dentro de la misma
    transacción. El asiento original nunca se modifica.
    """
    original = get_journal_entry(db, entry_id, for_update=True)
    if original.status is not JournalEntryStatus.POSTED:
        raise InvalidJournalEntryStateError(
            "Solo se pueden revertir asientos en estado POSTED; los borradores "
            "pueden anularse con void_journal_entry"
        )

    reversal_items: list[JournalItemCreate] = []
    for item in original.items:
        description = f"Reversión de {original.code}"
        if item.description:
            description += f": {item.description}"
        reversal_items.append(
            JournalItemCreate(
                account_id=item.account_id,
                debit=_money(item.credit),
                credit=_money(item.debit),
                description=description,
            )
        )

    reversal_date = date.today()
    code = _next_reversal_code(db, reversal_date.year)
    reversal = JournalEntry(
        code=code,
        entry_date=reversal_date,
        description=(
            f"Reversión del asiento {original.code}: {original.description}"
        ),
        reference_document=original.code,
        status=JournalEntryStatus.POSTED,
        posted_at=datetime.now(timezone.utc),
        created_by=created_by,
        items=_build_items(db, reversal_items),
    )
    with _atomic(db):
        _ensure_open_period(db, reversal.entry_date)
        _ensure_balanced(reversal)
        db.add(reversal)
    db.refresh(reversal)
    return reversal


def reject_journal_entry_mutation(db: Session, entry_id: int) -> None:
    """Bloquea explícitamente PATCH/DELETE sobre un asiento publicado."""
    entry = get_journal_entry(db, entry_id)
    raise ImmutableJournalEntryError(
        f"El asiento '{entry.code}' es inmutable: use void_journal_entry para "
        "borradores o reverse_journal_entry para asientos publicados"
    )


def build_journal_entry_post_response(
    entry: JournalEntry,
) -> JournalEntryPostResponse:
    """Construye la respuesta de publicación con los totales del comprobante."""
    total_debit, total_credit = _entry_totals(entry)
    return JournalEntryPostResponse(
        id=entry.id,
        code=entry.code,
        status=_as_status(entry.status),
        posted_at=entry.posted_at,  # type: ignore[arg-type]
        total_debit=total_debit,
        total_credit=total_credit,
    )


# --------------------------------------------------------------------------- #
# Integridad a nivel ORM (defensa en profundidad)
# --------------------------------------------------------------------------- #


def _parent_entry_status(connection: Any, journal_entry_id: int) -> Any:
    """Lee el estado del asiento padre desde la conexión en curso."""
    row = connection.execute(
        select(JournalEntry.status).where(JournalEntry.id == journal_entry_id)
    ).first()
    return _as_status(row[0]) if row is not None else None


def _previous_status(target: JournalEntry) -> Any:
    """Estado persisted del asiento antes del ``flush`` actual."""
    history = inspect(target).attrs.status.history
    if history.deleted:
        return _as_status(history.deleted[0])
    return _as_status(target.status)


@event.listens_for(JournalEntry, "before_update")
def _guard_journal_entry_update(mapper: Any, connection: Any, target: JournalEntry) -> None:  # noqa: ARG001
    """Solo un borrador puede cambiar: a ``POSTED``, a ``VOID`` o en sus datos."""
    previous = _previous_status(target)
    if previous is JournalEntryStatus.POSTED:
        raise ImmutableJournalEntryError(
            "Un asiento publicado no puede modificarse; registre una reversión"
        )
    if previous is JournalEntryStatus.VOID:
        raise ImmutableJournalEntryError(
            "Un asiento anulado no puede modificarse"
        )
    current = _as_status(target.status)
    if current not in _DRAFT_TRANSITIONS | {JournalEntryStatus.DRAFT}:
        raise InvalidJournalEntryStateError(
            f"Transición de estado no permitida: {previous} -> {current}"
        )


@event.listens_for(JournalEntry, "before_delete")
def _guard_journal_entry_delete(mapper: Any, connection: Any, target: JournalEntry) -> None:  # noqa: ARG001
    """Los asientos publicados no se eliminan físicamente."""
    if _as_status(target.status) is JournalEntryStatus.POSTED:
        raise ImmutableJournalEntryError(
            "Un asiento publicado no puede eliminarse; registre una reversión"
        )


@event.listens_for(JournalItem, "before_update")
def _guard_journal_item_update(mapper: Any, connection: Any, target: JournalItem) -> None:  # noqa: ARG001
    """Las líneas de un asiento publicado son inmutables."""
    if _parent_entry_status(connection, target.journal_entry_id) is JournalEntryStatus.POSTED:
        raise ImmutableJournalEntryError(
            "Las líneas de un asiento publicado no pueden modificarse"
        )


@event.listens_for(JournalItem, "before_delete")
def _guard_journal_item_delete(mapper: Any, connection: Any, target: JournalItem) -> None:  # noqa: ARG001
    """Las líneas de un asiento publicado no se eliminan."""
    if _parent_entry_status(connection, target.journal_entry_id) is JournalEntryStatus.POSTED:
        raise ImmutableJournalEntryError(
            "Las líneas de un asiento publicado no pueden eliminarse"
        )


@event.listens_for(Account, "before_delete")
def _guard_account_delete(mapper: Any, connection: Any, target: Account) -> None:  # noqa: ARG001
    """Espejo de la regla 8 para borrados que no pasen por el servicio."""
    children = connection.execute(
        select(Account.id).where(Account.parent_id == target.id).limit(1)
    ).first()
    if children is not None:
        raise AccountInUseError(
            "La cuenta tiene subcuentas; desactívela en lugar de eliminarla"
        )
    items = connection.execute(
        select(JournalItem.id).where(JournalItem.account_id == target.id).limit(1)
    ).first()
    if items is not None:
        raise AccountInUseError(
            "La cuenta tiene movimientos contables; desactívela en lugar de "
            "eliminarla"
        )
