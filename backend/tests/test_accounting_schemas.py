"""Pruebas unitarias rápidas de los esquemas Pydantic de ``accounting``.

No requieren base de datos: validan que el contrato rechace datos inválidos
antes de llegar a los servicios (Hito 2 de ``specs/accounting_spec.md``).
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite://")

from src.modules.accounting.models import (  # noqa: E402
    AccountBalanceStatus,
    AccountType,
    JournalEntryStatus,
)
from src.modules.accounting.schemas import (  # noqa: E402
    AccountCreate,
    AccountPayableCreate,
    AccountReceivableCreate,
    AccountResponse,
    AccountUpdate,
    BalanceSheetResponse,
    IncomeStatementResponse,
    JournalEntryCreate,
    JournalEntryPostResponse,
    JournalEntryResponse,
    JournalItemCreate,
    PaymentCreate,
    TrialBalanceResponse,
)

_TODAY = date(2026, 11, 19)
_CREATED_AT = datetime(2026, 11, 19, 10, 30)


def test_account_create_validates_code_and_account_type() -> None:
    account = AccountCreate(
        code="110505", name="Caja General", account_type=AccountType.ASSET
    )
    assert account.code == "110505"
    assert account.account_type is AccountType.ASSET
    assert account.is_active is True

    with pytest.raises(ValidationError):
        AccountCreate(code="caja", name="Caja", account_type=AccountType.ASSET)

    with pytest.raises(ValidationError):
        AccountCreate(code="110505", name="Caja", account_type="CASH")

    with pytest.raises(ValidationError):
        AccountCreate(
            code="1" * 31, name="Caja", account_type=AccountType.ASSET
        )

    with pytest.raises(ValidationError):
        AccountCreate(
            code="110505",
            name="Caja",
            account_type=AccountType.ASSET,
            is_active=True,
            injected="mass assignment",
        )


def test_account_update_requires_fields_and_allows_clearing_parent() -> None:
    with pytest.raises(ValidationError):
        AccountUpdate()

    with pytest.raises(ValidationError):
        AccountUpdate(name=None)

    account = AccountUpdate(parent_id=None, is_active=False)
    assert account.parent_id is None
    assert account.is_active is False

    with pytest.raises(ValidationError):
        AccountUpdate(code="codigo-invalido")


def test_account_response_is_built_from_orm_attributes() -> None:
    orm_account = SimpleNamespace(
        id=1,
        code="4135",
        name="Ventas",
        account_type=AccountType.REVENUE,
        parent_id=None,
        is_active=True,
        created_at=_CREATED_AT,
    )
    response = AccountResponse.model_validate(orm_account)
    assert response.id == 1
    assert response.account_type is AccountType.REVENUE
    assert response.model_dump()["created_at"] == _CREATED_AT


def test_journal_item_rejects_negative_and_double_sided_amounts() -> None:
    line = JournalItemCreate(account_id=1, debit=Decimal("500.00"))
    assert line.debit == Decimal("500.00")
    assert line.credit == Decimal("0.00")

    with pytest.raises(ValidationError):
        JournalItemCreate(account_id=1, debit=Decimal("-1.00"))

    with pytest.raises(ValidationError):
        JournalItemCreate(account_id=1, credit=Decimal("-0.01"))

    with pytest.raises(ValidationError):
        JournalItemCreate(
            account_id=1, debit=Decimal("500.00"), credit=Decimal("500.00")
        )

    with pytest.raises(ValidationError):
        JournalItemCreate(account_id=1, debit=500.0)

    with pytest.raises(ValidationError):
        JournalItemCreate(account_id=0, debit=Decimal("1.00"))


def test_journal_entry_requires_two_valid_lines() -> None:
    with pytest.raises(ValidationError):
        JournalEntryCreate(
            code="ASI-2026-0001",
            description="Asiento incompleto",
            items=[JournalItemCreate(account_id=1, debit=Decimal("100.00"))],
        )

    entry = JournalEntryCreate(
        code="ASI-2026-0001",
        entry_date=_TODAY,
        description="Venta al contado",
        items=[
            JournalItemCreate(account_id=1, debit=Decimal("500.00")),
            JournalItemCreate(account_id=2, credit=Decimal("500.00")),
        ],
    )
    assert len(entry.items) == 2
    assert entry.entry_date == _TODAY
    assert "status" not in JournalEntryCreate.model_fields

    with pytest.raises(ValidationError):
        JournalEntryCreate(
            code="asi-2026-0001",
            description="Código en minúsculas",
            items=[
                JournalItemCreate(account_id=1, debit=Decimal("1.00")),
                JournalItemCreate(account_id=2, credit=Decimal("1.00")),
            ],
        )


def test_journal_responses_use_strict_decimal_and_enum_status() -> None:
    response = JournalEntryPostResponse(
        id=1,
        code="ASI-2026-0001",
        status=JournalEntryStatus.POSTED,
        posted_at=_CREATED_AT,
        total_debit=Decimal("500.00"),
        total_credit=Decimal("500.00"),
    )
    assert response.status is JournalEntryStatus.POSTED

    with pytest.raises(ValidationError):
        JournalEntryPostResponse(
            id=1,
            code="ASI-2026-0001",
            status=JournalEntryStatus.POSTED,
            posted_at=_CREATED_AT,
            total_debit=500.0,
            total_credit=Decimal("500.00"),
        )

    orm_entry = SimpleNamespace(
        id=1,
        code="ASI-2026-0001",
        entry_date=_TODAY,
        description="Venta al contado",
        reference_document=None,
        status=JournalEntryStatus.DRAFT,
        created_by="admin",
        posted_at=None,
        created_at=_CREATED_AT,
        items=[
            SimpleNamespace(
                id=1,
                journal_entry_id=1,
                account_id=1,
                debit=Decimal("500.00"),
                credit=Decimal("0.00"),
                description=None,
            )
        ],
    )
    detail = JournalEntryResponse.model_validate(orm_entry)
    assert detail.items[0].debit == Decimal("500.00")


def test_receivable_and_payable_reject_paid_over_total() -> None:
    receivable = AccountReceivableCreate(
        customer_id=1,
        invoice_id=7,
        total_amount=Decimal("1000.00"),
        paid_amount=Decimal("400.00"),
        due_date=_TODAY,
    )
    assert receivable.paid_amount == Decimal("400.00")

    with pytest.raises(ValidationError):
        AccountReceivableCreate(
            customer_id=1,
            total_amount=Decimal("1000.00"),
            paid_amount=Decimal("1000.01"),
            due_date=_TODAY,
        )

    payable = AccountPayableCreate(
        supplier_id=2,
        bill_reference="FAC-2026-0001",
        total_amount=Decimal("800.00"),
        due_date=_TODAY,
    )
    assert payable.paid_amount == Decimal("0.00")

    with pytest.raises(ValidationError):
        AccountPayableCreate(
            supplier_id=2,
            bill_reference="FAC-2026-0001",
            total_amount=Decimal("800.00"),
            paid_amount=Decimal("800.01"),
            due_date=_TODAY,
        )

    with pytest.raises(ValidationError):
        AccountPayableCreate(
            supplier_id=2,
            bill_reference="FAC-2026-0001",
            total_amount=800.0,
            due_date=_TODAY,
        )

    assert AccountBalanceStatus.PARTIALLY_PAID.value == "PARTIALLY_PAID"


def test_payment_requires_exactly_one_target_and_positive_amount() -> None:
    payment = PaymentCreate(
        receivable_id=1,
        amount=Decimal("400.00"),
        payment_date=_TODAY,
        reference="TRANS-123",
    )
    assert payment.receivable_id == 1
    assert payment.payable_id is None

    with pytest.raises(ValidationError):
        PaymentCreate(amount=Decimal("400.00"))

    with pytest.raises(ValidationError):
        PaymentCreate(
            receivable_id=1, payable_id=2, amount=Decimal("400.00")
        )

    with pytest.raises(ValidationError):
        PaymentCreate(receivable_id=1, amount=Decimal("0.00"))

    with pytest.raises(ValidationError):
        PaymentCreate(receivable_id=1, amount=Decimal("-1.00"))

    with pytest.raises(ValidationError):
        PaymentCreate(receivable_id=1, amount=400.0)


def test_report_schemas_use_decimal_and_reject_floats() -> None:
    trial_balance = TrialBalanceResponse(
        lines=[
            {
                "account_id": 1,
                "code": "110505",
                "name": "Caja General",
                "account_type": AccountType.ASSET,
                "debit": Decimal("500.00"),
                "credit": Decimal("0.00"),
                "balance": Decimal("500.00"),
            }
        ],
        total_debit=Decimal("500.00"),
        total_credit=Decimal("500.00"),
    )
    assert trial_balance.total_debit == Decimal("500.00")

    with pytest.raises(ValidationError):
        TrialBalanceResponse(total_debit=500.0)

    balance_sheet = BalanceSheetResponse(
        total_assets=Decimal("500.00"),
        total_liabilities=Decimal("0.00"),
        total_equity=Decimal("500.00"),
        total_liabilities_and_equity=Decimal("500.00"),
        difference=Decimal("0.00"),
    )
    assert balance_sheet.difference == Decimal("0.00")

    with pytest.raises(ValidationError):
        BalanceSheetResponse(total_assets=500.0)

    income = IncomeStatementResponse(
        total_revenue=Decimal("500.00"),
        total_expenses=Decimal("200.00"),
        net_income=Decimal("300.00"),
    )
    assert income.net_income == Decimal("300.00")

    with pytest.raises(ValidationError):
        IncomeStatementResponse(net_income=300.0)
