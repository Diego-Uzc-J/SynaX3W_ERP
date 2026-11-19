"""Pruebas de integración contable con ``sales`` y ``purchasing`` (Hitos 4-5).

Verifica que los documentos comerciales generen asientos ``POSTED`` y saldos
CxC/CxP en la misma transacción, y que cualquier fallo al construir el asiento
o al actualizar el saldo revierta por completo la operación.
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
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
from src.modules.accounting import service as accounting_service  # noqa: E402
from src.modules.accounting.models import (  # noqa: E402
    Account,
    AccountBalanceStatus,
    AccountPayable,
    AccountReceivable,
    AccountType,
    JournalEntry,
    JournalEntryStatus,
    JournalItem,
    PaymentRecord,
)
from src.modules.accounting.schemas import (  # noqa: E402
    AccountCreate,
    PaymentCreate,
)
from src.modules.inventory.models import Product, Warehouse  # noqa: E402
from src.modules.purchasing.models import (  # noqa: E402
    GoodsReceipt,
    GoodsReceiptItem,
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseOrderStatus,
    Supplier,
    SupplierBill,
    SupplierBillStatus,
)
from src.modules.sales.models import (  # noqa: E402
    CreditNote,
    Customer,
    Invoice,
    InvoiceStatus,
    SalesOrder,
    SalesOrderStatus,
)

_ISSUE_DATE = date(2026, 11, 19)
_DUE_DATE = date(2026, 12, 19)


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
def chart(db_session: Session) -> dict[str, Account]:
    """PUC mínimo con los códigos por defecto que usa la automatización."""
    definitions = {
        "cash": ("110505", "Caja General", AccountType.ASSET),
        "receivable": ("130505", "Clientes", AccountType.ASSET),
        "revenue": ("4135", "Ventas", AccountType.REVENUE),
        "output_tax": ("240805", "IVA por pagar", AccountType.LIABILITY),
        "inventory": ("1435", "Inventario", AccountType.ASSET),
        "input_tax": ("135515", "IVA descontable", AccountType.ASSET),
        "payable": ("220505", "Proveedores", AccountType.LIABILITY),
    }
    accounts = {
        role: accounting_service.create_account(
            db_session,
            AccountCreate(code=code, name=name, account_type=kind),
        )
        for role, (code, name, kind) in definitions.items()
    }
    return accounts


@pytest.fixture()
def customer(db_session: Session) -> Customer:
    """Cliente activo con cupo suficiente."""
    entity = Customer(
        tax_id="900000001",
        company_name="Cliente Demo",
        contact_name="Ana Pérez",
        email="ana@example.com",
        phone=None,
        address="Calle 1",
        credit_limit=Decimal("10000.00"),
        is_active=True,
    )
    db_session.add(entity)
    db_session.commit()
    db_session.refresh(entity)
    return entity


@pytest.fixture()
def supplier(db_session: Session) -> Supplier:
    """Proveedor activo con 30 días de plazo."""
    entity = Supplier(
        tax_id="800000001",
        company_name="Proveedor Demo",
        contact_name="Luis López",
        email="luis@example.com",
        phone=None,
        address="Calle 2",
        payment_terms_days=30,
        is_active=True,
    )
    db_session.add(entity)
    db_session.commit()
    db_session.refresh(entity)
    return entity


@pytest.fixture()
def invoice(db_session: Session, customer: Customer) -> Invoice:
    """Factura directa de 1.200,00 sin pedido asociado."""
    entity = Invoice(
        code="FAC-2026-0001",
        sales_order_id=None,
        customer_id=customer.id,
        status=InvoiceStatus.ISSUED,
        issue_date=_ISSUE_DATE,
        due_date=_DUE_DATE,
        total=Decimal("1200.00"),
        balance_due=Decimal("1200.00"),
    )
    db_session.add(entity)
    db_session.commit()
    db_session.refresh(entity)
    return entity


@pytest.fixture()
def credit_note(db_session: Session, invoice: Invoice) -> CreditNote:
    """Nota crédito de 200,00 sobre la factura de prueba."""
    entity = CreditNote(
        code="NC-2026-0001",
        invoice_id=invoice.id,
        amount=Decimal("200.00"),
        reason="Devolución parcial",
        issue_date=_ISSUE_DATE,
    )
    db_session.add(entity)
    db_session.commit()
    db_session.refresh(entity)
    return entity


@pytest.fixture()
def purchase_document(
    db_session: Session, supplier: Supplier
) -> tuple[GoodsReceipt, SupplierBill]:
    """Recepción y factura de proveedor con origen en una OC."""
    warehouse = Warehouse(
        code="WH-01", name="Bodega principal", address=None, is_active=True
    )
    product = Product(
        sku="P-001",
        name="Producto demo",
        description=None,
        unit_price=Decimal("100.00"),
        minimum_stock=0,
        is_active=True,
    )
    db_session.add_all([warehouse, product])
    db_session.flush()

    order = PurchaseOrder(
        code="OC-2026-0001",
        supplier_id=supplier.id,
        status=PurchaseOrderStatus.APPROVED,
        issue_date=_ISSUE_DATE,
        expected_delivery_date=_DUE_DATE,
        subtotal=Decimal("800.00"),
        tax_amount=Decimal("0.00"),
        total=Decimal("800.00"),
    )
    db_session.add(order)
    db_session.flush()

    order_item = PurchaseOrderItem(
        purchase_order_id=order.id,
        product_id=product.id,
        quantity=10,
        received_quantity=10,
        unit_price=Decimal("80.00"),
        tax_rate=Decimal("0.00"),
        subtotal=Decimal("800.00"),
    )
    db_session.add(order_item)
    db_session.flush()

    receipt = GoodsReceipt(
        code="REC-2026-0001",
        purchase_order_id=order.id,
        warehouse_id=warehouse.id,
        receipt_date=_ISSUE_DATE,
        received_by="admin",
        notes=None,
    )
    receipt.items.append(
        GoodsReceiptItem(purchase_order_item_id=order_item.id, quantity=10)
    )
    db_session.add(receipt)
    db_session.flush()

    bill = SupplierBill(
        code="FCP-2026-0001",
        supplier_id=supplier.id,
        purchase_order_id=order.id,
        goods_receipt_id=receipt.id,
        supplier_invoice_number="PROV-2026-001",
        status=SupplierBillStatus.PENDING,
        issue_date=_ISSUE_DATE,
        due_date=_DUE_DATE,
        subtotal=Decimal("900.00"),
        tax_amount=Decimal("0.00"),
        total=Decimal("900.00"),
        balance_due=Decimal("900.00"),
    )
    db_session.add(bill)
    db_session.commit()
    db_session.refresh(receipt)
    db_session.refresh(bill)
    return receipt, bill


def _count(db: Session, model: Any) -> int:
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


def _lines(entry: JournalEntry) -> list[tuple[str, Decimal, Decimal]]:
    return [(item.account.code, item.debit, item.credit) for item in entry.items]


# --------------------------------------------------------------------------- #
# Automatización desde sales
# --------------------------------------------------------------------------- #


def test_invoice_posts_entry_and_creates_receivable(
    db_session: Session, chart: dict[str, Account], invoice: Invoice
) -> None:
    result = accounting_service.post_sales_invoice_accounting(db_session, invoice.id)

    assert result.journal_entry.status is JournalEntryStatus.POSTED
    assert result.journal_entry.posted_at is not None
    assert result.journal_entry.reference_document == invoice.code
    assert _lines(result.journal_entry) == [
        ("130505", Decimal("1200.00"), Decimal("0.00")),
        ("4135", Decimal("0.00"), Decimal("1200.00")),
    ]

    balance = result.balance
    assert isinstance(balance, AccountReceivable)
    assert balance.customer_id == invoice.customer_id
    assert balance.invoice_id == invoice.id
    assert balance.total_amount == Decimal("1200.00")
    assert balance.paid_amount == Decimal("0.00")
    assert balance.status is AccountBalanceStatus.PENDING
    assert balance.journal_entry_id == result.journal_entry.id

    repeated = accounting_service.post_sales_invoice_accounting(db_session, invoice.id)
    assert repeated.journal_entry.id == result.journal_entry.id
    assert _count(db_session, JournalEntry) == 1
    assert _count(db_session, AccountReceivable) == 1


def test_invoice_with_tax_splits_revenue_and_tax_lines(
    db_session: Session, chart: dict[str, Account], customer: Customer
) -> None:
    order = SalesOrder(
        code="PED-2026-0001",
        customer_id=customer.id,
        status=SalesOrderStatus.CONFIRMED,
        issue_date=_ISSUE_DATE,
        valid_until=None,
        subtotal=Decimal("1000.00"),
        tax_amount=Decimal("190.00"),
        total=Decimal("1190.00"),
    )
    db_session.add(order)
    db_session.flush()
    invoice_with_tax = Invoice(
        code="FAC-2026-0002",
        sales_order_id=order.id,
        customer_id=customer.id,
        status=InvoiceStatus.ISSUED,
        issue_date=_ISSUE_DATE,
        due_date=_DUE_DATE,
        total=Decimal("1190.00"),
        balance_due=Decimal("1190.00"),
    )
    db_session.add(invoice_with_tax)
    db_session.commit()

    result = accounting_service.post_sales_invoice_accounting(
        db_session, invoice_with_tax.id
    )
    assert _lines(result.journal_entry) == [
        ("130505", Decimal("1190.00"), Decimal("0.00")),
        ("4135", Decimal("0.00"), Decimal("1000.00")),
        ("240805", Decimal("0.00"), Decimal("190.00")),
    ]


def test_credit_note_posts_reversal_and_reduces_receivable(
    db_session: Session,
    chart: dict[str, Account],
    invoice: Invoice,
    credit_note: CreditNote,
) -> None:
    accounting_service.post_sales_invoice_accounting(db_session, invoice.id)
    result = accounting_service.post_sales_credit_note_accounting(
        db_session, credit_note.id
    )

    assert result.journal_entry.status is JournalEntryStatus.POSTED
    assert _lines(result.journal_entry) == [
        ("4135", Decimal("200.00"), Decimal("0.00")),
        ("130505", Decimal("0.00"), Decimal("200.00")),
    ]
    assert isinstance(result.balance, AccountReceivable)
    assert result.balance.total_amount == Decimal("1000.00")
    assert result.balance.status is AccountBalanceStatus.PENDING
    assert _count(db_session, JournalEntry) == 2
    assert _count(db_session, AccountReceivable) == 1


def test_inactive_account_reverts_invoice_integration(
    db_session: Session, chart: dict[str, Account], invoice: Invoice
) -> None:
    accounting_service.deactivate_account(db_session, chart["revenue"].id)

    with pytest.raises(accounting_service.InactiveAccountError):
        accounting_service.post_sales_invoice_accounting(db_session, invoice.id)

    assert _count(db_session, JournalEntry) == 0
    assert _count(db_session, JournalItem) == 0
    assert _count(db_session, AccountReceivable) == 0


def test_failure_building_entry_reverts_invoice_integration(
    db_session: Session,
    chart: dict[str, Account],
    invoice: Invoice,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("fallo forzado al generar el asiento")

    monkeypatch.setattr(accounting_service, "_ensure_balanced", boom)

    with pytest.raises(RuntimeError, match="fallo forzado"):
        accounting_service.post_sales_invoice_accounting(db_session, invoice.id)

    assert _count(db_session, JournalEntry) == 0
    assert _count(db_session, JournalItem) == 0
    assert _count(db_session, AccountReceivable) == 0


# --------------------------------------------------------------------------- #
# Automatización desde purchasing
# --------------------------------------------------------------------------- #


def test_receipt_and_bill_post_entries_and_create_payables(
    db_session: Session,
    chart: dict[str, Account],
    purchase_document: tuple[GoodsReceipt, SupplierBill],
) -> None:
    receipt, bill = purchase_document

    receipt_result = accounting_service.post_purchase_receipt_accounting(
        db_session, receipt.id
    )
    assert receipt_result.journal_entry.status is JournalEntryStatus.POSTED
    assert _lines(receipt_result.journal_entry) == [
        ("1435", Decimal("800.00"), Decimal("0.00")),
        ("220505", Decimal("0.00"), Decimal("800.00")),
    ]
    assert isinstance(receipt_result.balance, AccountPayable)
    assert receipt_result.balance.bill_reference == receipt.code
    assert receipt_result.balance.total_amount == Decimal("800.00")
    assert receipt_result.balance.due_date == _ISSUE_DATE + timedelta(days=30)

    bill_result = accounting_service.post_supplier_bill_accounting(db_session, bill.id)
    assert bill_result.journal_entry.status is JournalEntryStatus.POSTED
    assert _lines(bill_result.journal_entry) == [
        ("1435", Decimal("900.00"), Decimal("0.00")),
        ("220505", Decimal("0.00"), Decimal("900.00")),
    ]
    assert isinstance(bill_result.balance, AccountPayable)
    assert bill_result.balance.bill_reference == bill.code
    assert bill_result.balance.total_amount == Decimal("900.00")
    assert _count(db_session, JournalEntry) == 2
    assert _count(db_session, AccountPayable) == 2


def test_purchase_bill_with_tax_splits_inventory_and_tax_lines(
    db_session: Session,
    chart: dict[str, Account],
    purchase_document: tuple[GoodsReceipt, SupplierBill],
) -> None:
    receipt, original_bill = purchase_document
    # Los importes de una factura son inmutables: se crea una segunda factura
    # con impuestos en lugar de modificar la del fixture.
    bill = SupplierBill(
        code="FCP-2026-0002",
        supplier_id=original_bill.supplier_id,
        purchase_order_id=original_bill.purchase_order_id,
        goods_receipt_id=receipt.id,
        supplier_invoice_number="PROV-2026-002",
        status=SupplierBillStatus.PENDING,
        issue_date=_ISSUE_DATE,
        due_date=_DUE_DATE,
        subtotal=Decimal("1000.00"),
        tax_amount=Decimal("190.00"),
        total=Decimal("1190.00"),
        balance_due=Decimal("1190.00"),
    )
    db_session.add(bill)
    db_session.commit()
    db_session.refresh(bill)

    result = accounting_service.post_supplier_bill_accounting(db_session, bill.id)
    assert _lines(result.journal_entry) == [
        ("1435", Decimal("1000.00"), Decimal("0.00")),
        ("220505", Decimal("0.00"), Decimal("1190.00")),
        ("135515", Decimal("190.00"), Decimal("0.00")),
    ]


# --------------------------------------------------------------------------- #
# Cartera: cobros y pagos
# --------------------------------------------------------------------------- #


def test_receivable_payment_partial_then_full(
    db_session: Session, chart: dict[str, Account], invoice: Invoice
) -> None:
    accounting_service.post_sales_invoice_accounting(db_session, invoice.id)
    receivable = accounting_service.list_account_receivables(db_session)[0]

    first = accounting_service.register_receivable_payment(
        db_session,
        PaymentCreate(
            receivable_id=receivable.id,
            amount=Decimal("400.00"),
            reference="COB-1",
        ),
    )
    assert first.balance.paid_amount == Decimal("400.00")
    assert first.balance.status is AccountBalanceStatus.PARTIALLY_PAID
    assert first.payment.amount == Decimal("400.00")
    assert first.payment.reference == "COB-1"
    assert _lines(first.journal_entry) == [
        ("110505", Decimal("400.00"), Decimal("0.00")),
        ("130505", Decimal("0.00"), Decimal("400.00")),
    ]

    second = accounting_service.register_receivable_payment(
        db_session, first.balance.id, Decimal("800.00"), reference="COB-2"
    )
    assert second.balance.paid_amount == Decimal("1200.00")
    assert second.balance.status is AccountBalanceStatus.PAID
    assert _count(db_session, PaymentRecord) == 2
    assert _count(db_session, JournalEntry) == 3  # factura + 2 cobros
    assert [record.reference for record in accounting_service.list_payment_records(db_session)] == [
        "COB-1",
        "COB-2",
    ]


def test_payable_payment_partial_then_full(
    db_session: Session,
    chart: dict[str, Account],
    purchase_document: tuple[GoodsReceipt, SupplierBill],
) -> None:
    _, bill = purchase_document
    accounting_service.post_supplier_bill_accounting(db_session, bill.id)
    payable = accounting_service.list_account_payables(db_session)[0]

    first = accounting_service.register_payable_payment(
        db_session, payable.id, Decimal("300.00"), reference="PAG-1"
    )
    assert first.balance.paid_amount == Decimal("300.00")
    assert first.balance.status is AccountBalanceStatus.PARTIALLY_PAID
    assert _lines(first.journal_entry) == [
        ("220505", Decimal("300.00"), Decimal("0.00")),
        ("110505", Decimal("0.00"), Decimal("300.00")),
    ]

    second = accounting_service.register_payable_payment(
        db_session, payable.id, Decimal("600.00")
    )
    assert second.balance.paid_amount == Decimal("900.00")
    assert second.balance.status is AccountBalanceStatus.PAID
    assert _count(db_session, PaymentRecord) == 2


def test_invalid_payment_amounts_do_not_mutate(
    db_session: Session, chart: dict[str, Account], invoice: Invoice
) -> None:
    accounting_service.post_sales_invoice_accounting(db_session, invoice.id)
    receivable = accounting_service.list_account_receivables(db_session)[0]
    entries_before = _count(db_session, JournalEntry)

    with pytest.raises(accounting_service.InvalidSourceDocumentError):
        accounting_service.register_receivable_payment(
            db_session, receivable.id, Decimal("0.00")
        )
    with pytest.raises(accounting_service.InvalidSourceDocumentError):
        accounting_service.register_receivable_payment(
            db_session, receivable.id, Decimal("1200.01")
        )

    assert receivable.paid_amount == Decimal("0.00")
    assert receivable.status is AccountBalanceStatus.PENDING
    assert _count(db_session, PaymentRecord) == 0
    assert _count(db_session, JournalEntry) == entries_before


def test_failure_generating_payment_entry_reverts_everything(
    db_session: Session,
    chart: dict[str, Account],
    invoice: Invoice,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    accounting_service.post_sales_invoice_accounting(db_session, invoice.id)
    receivable = accounting_service.list_account_receivables(db_session)[0]
    entries_before = _count(db_session, JournalEntry)

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("fallo forzado al generar el asiento del cobro")

    monkeypatch.setattr(accounting_service, "_build_items", boom)

    with pytest.raises(RuntimeError, match="fallo forzado"):
        accounting_service.register_receivable_payment(
            db_session, receivable.id, Decimal("400.00")
        )

    assert _count(db_session, PaymentRecord) == 0
    assert _count(db_session, JournalEntry) == entries_before
    assert receivable.paid_amount == Decimal("0.00")
    assert receivable.status is AccountBalanceStatus.PENDING


def test_failure_updating_balance_reverts_payment_and_entry(
    db_session: Session,
    chart: dict[str, Account],
    invoice: Invoice,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    accounting_service.post_sales_invoice_accounting(db_session, invoice.id)
    receivable = accounting_service.list_account_receivables(db_session)[0]
    entries_before = _count(db_session, JournalEntry)

    def fail_after_partial_update(
        balance: AccountReceivable | AccountPayable, amount: Decimal
    ) -> None:
        balance.paid_amount = accounting_service._money(
            accounting_service._money(balance.paid_amount) + amount
        )
        raise RuntimeError("fallo forzado al actualizar el saldo")

    monkeypatch.setattr(
        accounting_service, "_apply_payment_to_balance", fail_after_partial_update
    )

    with pytest.raises(RuntimeError, match="fallo forzado"):
        accounting_service.register_receivable_payment(
            db_session, receivable.id, Decimal("400.00")
        )

    assert _count(db_session, PaymentRecord) == 0
    assert _count(db_session, JournalEntry) == entries_before
    db_session.refresh(receivable)
    assert receivable.paid_amount == Decimal("0.00")
    assert receivable.status is AccountBalanceStatus.PENDING
