"""Modelos de dominio del módulo de Finanzas y Contabilidad.

Implementa las entidades descritas en ``specs/accounting_spec.md`` (sección 2):
``Account``, ``JournalEntry``, ``JournalItem``, ``AccountReceivable``,
``AccountPayable``, ``PaymentRecord`` y ``AccountingPeriod``.

Convenciones alineadas con ``inventory``, ``sales`` y ``purchasing``:

- claves primarias ``Integer`` y fechas ``Date``/``DateTime(timezone=True)``;
- importes ``Numeric(14, 2)`` con ``CHECK`` de no negatividad;
- enums nativos de PostgreSQL con los valores del contrato;
- ``ON DELETE RESTRICT`` para documentos financieros y cuentas con historial;
  ``CASCADE`` solo en las líneas dependientes de su asiento;
- ``created_by`` se guarda como texto (identificador o nombre del usuario),
  igual que ``inventory.StockMovement.created_by`` y
  ``purchasing.GoodsReceipt.received_by``, para no acoplar el asiento a la
  tabla ``users``.

La clase declarativa ``Base`` es transversal y vive en ``src.core.database``.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum as PyEnum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.core.database import Base
from src.modules.purchasing.models import Supplier
from src.modules.sales.models import Customer, Invoice


class AccountType(str, PyEnum):
    """Clasificación de una cuenta del Plan Único de Cuentas (PUC)."""

    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    REVENUE = "REVENUE"
    EXPENSE = "EXPENSE"


class JournalEntryStatus(str, PyEnum):
    """Estados del ciclo de vida de un comprobante de diario."""

    DRAFT = "DRAFT"
    POSTED = "POSTED"
    VOID = "VOID"


class AccountBalanceStatus(str, PyEnum):
    """Estados compartidos por la cartera por cobrar y por pagar."""

    PENDING = "PENDING"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    OVERDUE = "OVERDUE"


#: Tipo enum nativo reutilizable con los valores del contrato.
ACCOUNT_TYPE_TYPE = SAEnum(
    AccountType,
    name="account_type",
    native_enum=True,
    validate_strings=True,
)

#: Tipo enum nativo reutilizable con los valores del contrato.
JOURNAL_ENTRY_STATUS_TYPE = SAEnum(
    JournalEntryStatus,
    name="journal_entry_status",
    native_enum=True,
    validate_strings=True,
)

#: Tipo enum nativo reutilizable por CxC y CxP (mismo dominio en la spec).
ACCOUNT_BALANCE_STATUS_TYPE = SAEnum(
    AccountBalanceStatus,
    name="account_balance_status",
    native_enum=True,
    validate_strings=True,
)

#: Importes monetarios del módulo (hasta 999 999 999 999.99).
MONEY = Numeric(14, 2)


class Account(Base):
    """Cuenta contable del Plan Único de Cuentas, jerárquica y opcionalmente activa."""

    __tablename__ = "accounts"
    __table_args__ = (
        Index("ix_accounts_name", "name"),
        Index("ix_accounts_parent_id", "parent_id"),
        Index("ix_accounts_account_type", "account_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(
        String(30), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    account_type: Mapped[AccountType] = mapped_column(
        ACCOUNT_TYPE_TYPE, nullable=False
    )
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relación autoreferencial: RESTRICT garantiza la regla 8 de la spec
    # (una cuenta con subcuentas no se elimina, solo se desactiva).
    parent: Mapped[Account | None] = relationship(
        remote_side=[id], back_populates="children"
    )
    # ``passive_deletes=True`` evita que SQLAlchemy intente desvincular hijos o
    # líneas (UPDATE ... SET NULL) antes del DELETE: la FK es RESTRICT y la
    # validación de borrado vive en el servicio y en los listeners del servicio.
    children: Mapped[list[Account]] = relationship(
        back_populates="parent", passive_deletes=True
    )
    journal_items: Mapped[list[JournalItem]] = relationship(
        back_populates="account", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return f"<Account id={self.id!r} code={self.code!r} type={self.account_type!r}>"


class JournalEntry(Base):
    """Encabezado inmutable de un asiento contable (libro diario)."""

    __tablename__ = "journal_entries"
    __table_args__ = (
        Index("ix_journal_entries_entry_date", "entry_date"),
        Index("ix_journal_entries_status", "status"),
        Index("ix_journal_entries_created_by", "created_by"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(
        String(30), unique=True, nullable=False, index=True
    )
    entry_date: Mapped[date] = mapped_column(
        Date, nullable=False, default=date.today, server_default=func.current_date()
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    reference_document: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[JournalEntryStatus] = mapped_column(
        JOURNAL_ENTRY_STATUS_TYPE,
        nullable=False,
        default=JournalEntryStatus.DRAFT,
        server_default=JournalEntryStatus.DRAFT.value,
    )
    created_by: Mapped[str | None] = mapped_column(String(150), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    items: Mapped[list[JournalItem]] = relationship(
        back_populates="entry",
        cascade="all, delete-orphan",
    )
    receivables: Mapped[list[AccountReceivable]] = relationship(
        back_populates="journal_entry"
    )
    payables: Mapped[list[AccountPayable]] = relationship(
        back_populates="journal_entry"
    )
    payments: Mapped[list[PaymentRecord]] = relationship(
        back_populates="journal_entry"
    )

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return (
            f"<JournalEntry id={self.id!r} code={self.code!r} status={self.status!r}>"
        )


class JournalItem(Base):
    """Línea de partida doble: un importe al debe o al haber, nunca ambos."""

    __tablename__ = "journal_items"
    __table_args__ = (
        CheckConstraint("debit >= 0", name="ck_journal_items_debit_non_negative"),
        CheckConstraint("credit >= 0", name="ck_journal_items_credit_non_negative"),
        CheckConstraint(
            "NOT (debit > 0 AND credit > 0)",
            name="ck_journal_items_single_side",
        ),
        Index("ix_journal_items_journal_entry_id", "journal_entry_id"),
        Index("ix_journal_items_account_id", "account_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    journal_entry_id: Mapped[int] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="CASCADE"), nullable=False
    )
    # Una cuenta con movimientos no se elimina físicamente (regla 8).
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    debit: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    credit: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    entry: Mapped[JournalEntry] = relationship(back_populates="items")
    account: Mapped[Account] = relationship(back_populates="journal_items")

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return (
            f"<JournalItem id={self.id!r} entry_id={self.journal_entry_id!r} "
            f"debit={self.debit!r} credit={self.credit!r}>"
        )


class AccountReceivable(Base):
    """Cuenta por cobrar derivada de una factura de ventas."""

    __tablename__ = "account_receivables"
    __table_args__ = (
        CheckConstraint(
            "total_amount >= 0", name="ck_account_receivables_total_non_negative"
        ),
        CheckConstraint(
            "paid_amount >= 0", name="ck_account_receivables_paid_non_negative"
        ),
        CheckConstraint(
            "paid_amount <= total_amount",
            name="ck_account_receivables_paid_not_over_total",
        ),
        Index("ix_account_receivables_customer_id", "customer_id"),
        Index("ix_account_receivables_invoice_id", "invoice_id"),
        Index("ix_account_receivables_journal_entry_id", "journal_entry_id"),
        Index("ix_account_receivables_status", "status"),
        Index("ix_account_receivables_due_date", "due_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=True
    )
    journal_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="RESTRICT"), nullable=True
    )
    total_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[AccountBalanceStatus] = mapped_column(
        ACCOUNT_BALANCE_STATUS_TYPE,
        nullable=False,
        default=AccountBalanceStatus.PENDING,
        server_default=AccountBalanceStatus.PENDING.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    customer: Mapped[Customer] = relationship()
    invoice: Mapped[Invoice | None] = relationship()
    journal_entry: Mapped[JournalEntry | None] = relationship(
        back_populates="receivables"
    )
    payments: Mapped[list[PaymentRecord]] = relationship(back_populates="receivable")

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return (
            f"<AccountReceivable id={self.id!r} customer_id={self.customer_id!r} "
            f"total_amount={self.total_amount!r} status={self.status!r}>"
        )


class AccountPayable(Base):
    """Cuenta por pagar derivada de una factura de proveedor."""

    __tablename__ = "account_payables"
    __table_args__ = (
        CheckConstraint(
            "total_amount >= 0", name="ck_account_payables_total_non_negative"
        ),
        CheckConstraint(
            "paid_amount >= 0", name="ck_account_payables_paid_non_negative"
        ),
        CheckConstraint(
            "paid_amount <= total_amount",
            name="ck_account_payables_paid_not_over_total",
        ),
        Index("ix_account_payables_supplier_id", "supplier_id"),
        Index("ix_account_payables_journal_entry_id", "journal_entry_id"),
        Index("ix_account_payables_status", "status"),
        Index("ix_account_payables_due_date", "due_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False
    )
    bill_reference: Mapped[str] = mapped_column(String(100), nullable=False)
    journal_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="RESTRICT"), nullable=True
    )
    total_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    paid_amount: Mapped[Decimal] = mapped_column(
        MONEY, nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[AccountBalanceStatus] = mapped_column(
        ACCOUNT_BALANCE_STATUS_TYPE,
        nullable=False,
        default=AccountBalanceStatus.PENDING,
        server_default=AccountBalanceStatus.PENDING.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    supplier: Mapped[Supplier] = relationship()
    journal_entry: Mapped[JournalEntry | None] = relationship(
        back_populates="payables"
    )
    payments: Mapped[list[PaymentRecord]] = relationship(back_populates="payable")

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return (
            f"<AccountPayable id={self.id!r} supplier_id={self.supplier_id!r} "
            f"bill_reference={self.bill_reference!r} status={self.status!r}>"
        )


class PaymentRecord(Base):
    """Abono o pago aplicado a una CxC o CxP, con trazabilidad contable."""

    __tablename__ = "payment_records"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payment_records_amount_positive"),
        CheckConstraint(
            "receivable_id IS NOT NULL OR payable_id IS NOT NULL",
            name="ck_payment_records_has_target",
        ),
        CheckConstraint(
            "NOT (receivable_id IS NOT NULL AND payable_id IS NOT NULL)",
            name="ck_payment_records_single_target",
        ),
        Index("ix_payment_records_receivable_id", "receivable_id"),
        Index("ix_payment_records_payable_id", "payable_id"),
        Index("ix_payment_records_journal_entry_id", "journal_entry_id"),
        Index("ix_payment_records_payment_date", "payment_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receivable_id: Mapped[int | None] = mapped_column(
        ForeignKey("account_receivables.id", ondelete="RESTRICT"), nullable=True
    )
    payable_id: Mapped[int | None] = mapped_column(
        ForeignKey("account_payables.id", ondelete="RESTRICT"), nullable=True
    )
    journal_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("journal_entries.id", ondelete="RESTRICT"), nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    payment_date: Mapped[date] = mapped_column(
        Date, nullable=False, default=date.today, server_default=func.current_date()
    )
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    receivable: Mapped[AccountReceivable | None] = relationship(
        back_populates="payments"
    )
    payable: Mapped[AccountPayable | None] = relationship(back_populates="payments")
    journal_entry: Mapped[JournalEntry | None] = relationship(
        back_populates="payments"
    )

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return (
            f"<PaymentRecord id={self.id!r} amount={self.amount!r} "
            f"receivable_id={self.receivable_id!r} payable_id={self.payable_id!r}>"
        )


class AccountingPeriod(Base):
    """Periodo contable que bloquea contabilizaciones retroactivas al cerrarse."""

    __tablename__ = "accounting_periods"
    __table_args__ = (
        CheckConstraint(
            "start_date <= end_date", name="ck_accounting_periods_valid_range"
        ),
        Index("ix_accounting_periods_start_date", "start_date"),
        Index("ix_accounting_periods_end_date", "end_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(
        String(20), unique=True, nullable=False, index=True
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_closed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return (
            f"<AccountingPeriod id={self.id!r} name={self.name!r} "
            f"is_closed={self.is_closed!r}>"
        )


__all__ = [
    "ACCOUNT_BALANCE_STATUS_TYPE",
    "ACCOUNT_TYPE_TYPE",
    "JOURNAL_ENTRY_STATUS_TYPE",
    "MONEY",
    "Account",
    "AccountBalanceStatus",
    "AccountPayable",
    "AccountReceivable",
    "AccountType",
    "AccountingPeriod",
    "JournalEntry",
    "JournalEntryStatus",
    "JournalItem",
    "PaymentRecord",
]
