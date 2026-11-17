"""Pruebas de aceptación del módulo ``purchasing``.

Cubren los escenarios críticos de ``specs/purchasing_spec.md`` en dos niveles:

* **Servicios:** recepción exitosa con impacto en stock y cierre de la OC,
  proveedor inactivo, ``tax_id`` duplicado, sobre-recepción, inmutabilidad de
  la recepción, producto inactivo en una línea de OC, facturación, pagos y
  secuenciación de códigos ``OC-YYYY-XXXX`` / ``REC-YYYY-XXXX``.
* **HTTP/RBAC:** los mismos escenarios a través del router real
  (``TestClient``), verificando los códigos de estado 201/400/409 y el rechazo
  403 a usuarios sin los roles ``PURCHASING`` o ``ADMINISTRATOR``.

Todo usa SQLite en memoria. Las pruebas de servicio comprueban directamente el
``status_code`` de las excepciones HTTP de dominio; las de HTTP validan que el
manejador registrado en ``src.main`` las traduce igual. Las recepciones se
validan contra las tablas de ``inventory`` para confirmar la atomicidad.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Generator
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ["DATABASE_URL"] = "sqlite://"

from src.core.database import Base, get_db  # noqa: E402
from src.core.security import create_access_token, hash_password  # noqa: E402
from src.main import app  # noqa: E402
from src.modules.inventory import services as inventory_services  # noqa: E402
from src.modules.inventory.models import (  # noqa: E402
    MovementType,
    Product,
    Stock,
    StockMovement,
    Warehouse,
)
from src.modules.purchasing.models import (  # noqa: E402
    GoodsReceipt,
    GoodsReceiptItem,
    PurchaseOrder,
    PurchaseOrderStatus,
    Supplier,
    SupplierBill,
    SupplierBillPayment,
    SupplierBillStatus,
)
from src.modules.purchasing.schemas import (  # noqa: E402
    GoodsReceiptCreate,
    GoodsReceiptItemCreate,
    PurchaseOrderCreate,
    PurchaseOrderItemCreate,
    PurchaseOrderUpdate,
    SupplierBillCreate,
    SupplierBillPaymentCreate,
    SupplierCreate,
    SupplierUpdate,
)
from src.modules.purchasing.services import (  # noqa: E402
    DuplicateResourceError,
    ImmutableBillError,
    ImmutableReceiptError,
    InactiveProductError,
    InactiveSupplierError,
    InvalidBillError,
    InvalidBillStateError,
    InvalidOrderDataError,
    InvalidOrderStateError,
    OverReceiptError,
    ResourceNotFoundError,
    approve_purchase_order,
    cancel_purchase_order,
    create_goods_receipt,
    create_purchase_order,
    create_supplier,
    create_supplier_bill,
    deactivate_supplier,
    force_close_purchase_order,
    get_goods_receipt,
    get_purchase_order,
    get_supplier_bill,
    list_bill_payments,
    list_goods_receipts,
    list_supplier_bills,
    list_suppliers,
    register_bill_payment,
    reject_bill_mutation,
    update_purchase_order,
    update_supplier,
    void_supplier_bill,
)
from src.modules.users.models import Role, RoleEnum, User  # noqa: E402

_TODAY = date.today()


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


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
def supplier(db_session: Session) -> Supplier:
    """Proveedor activo con plazos de pago de 30 días."""
    created = create_supplier(db_session, supplier_payload())
    return created


@pytest.fixture()
def product(db_session: Session) -> Product:
    """Producto activo usado en las líneas de las órdenes."""
    item = Product(
        sku="LAP-001",
        name="Laptop Industrial",
        unit_price=Decimal("1250.00"),
        is_active=True,
    )
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


@pytest.fixture()
def warehouse(db_session: Session) -> Warehouse:
    """Bodega destino de los movimientos ``INBOUND`` de las recepciones."""
    item = Warehouse(code="BOD-PRINCIPAL", name="Bodega Principal", is_active=True)
    db_session.add(item)
    db_session.commit()
    db_session.refresh(item)
    return item


@pytest.fixture()
def approved_order(
    db_session: Session, supplier: Supplier, product: Product
) -> PurchaseOrder:
    """OC aprobada de 20 unidades, lista para recibir mercancía."""
    order = create_purchase_order(
        db_session, order_payload(supplier.id, product.id, quantity=20)
    )
    order.status = PurchaseOrderStatus.APPROVED
    db_session.commit()
    db_session.refresh(order)
    return order


# --------------------------------------------------------------------------- #
# Ayudas
# --------------------------------------------------------------------------- #


def supplier_payload(**overrides: object) -> SupplierCreate:
    """Datos válidos para registrar un proveedor."""
    values: dict[str, object] = {
        "tax_id": "800987654-3",
        "company_name": "Proveedores del Norte S.A.S.",
        "contact_name": "María Gómez",
        "email": "ventas@proveedoresnorte.com",
        "address": "Calle 10 # 20-30",
        "payment_terms_days": 30,
    }
    values.update(overrides)
    return SupplierCreate(**values)  # type: ignore[arg-type]


def order_payload(
    supplier_id: int,
    product_id: int,
    *,
    quantity: int = 3,
    **overrides: object,
) -> PurchaseOrderCreate:
    """Datos válidos para crear una OC de una línea."""
    values: dict[str, object] = {
        "supplier_id": supplier_id,
        "issue_date": _TODAY,
        "expected_delivery_date": _TODAY + timedelta(days=15),
        "items": [
            PurchaseOrderItemCreate(
                product_id=product_id,
                quantity=quantity,
                unit_price=Decimal("1250.00"),
                tax_rate=Decimal("19.00"),
            )
        ],
    }
    values.update(overrides)
    return PurchaseOrderCreate(**values)  # type: ignore[arg-type]


def receipt_payload(
    order: PurchaseOrder,
    warehouse_id: int,
    *,
    quantity: int | None = None,
    **overrides: object,
) -> GoodsReceiptCreate:
    """Datos válidos para recibir la primera línea de una OC."""
    line = order.items[0]
    values: dict[str, object] = {
        "purchase_order_id": order.id,
        "warehouse_id": warehouse_id,
        "receipt_date": _TODAY,
        "received_by": "almacenista-1",
        "items": [
            GoodsReceiptItemCreate(
                purchase_order_item_id=line.id,
                quantity=line.quantity if quantity is None else quantity,
            )
        ],
    }
    values.update(overrides)
    return GoodsReceiptCreate(**values)  # type: ignore[arg-type]


def bill_payload(
    supplier_id: int,
    *,
    purchase_order_id: int | None = None,
    goods_receipt_id: int | None = None,
    subtotal: Decimal = Decimal("25000.00"),
    tax_amount: Decimal = Decimal("4750.00"),
    **overrides: object,
) -> SupplierBillCreate:
    """Datos de una factura coherente con 20 unidades a 1250 + 19% de IVA."""
    values: dict[str, object] = {
        "supplier_id": supplier_id,
        "purchase_order_id": purchase_order_id,
        "goods_receipt_id": goods_receipt_id,
        "supplier_invoice_number": "F-2026-0042",
        "issue_date": _TODAY,
        "subtotal": subtotal,
        "tax_amount": tax_amount,
    }
    values.update(overrides)
    return SupplierBillCreate(**values)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Proveedores
# --------------------------------------------------------------------------- #


def test_create_supplier_and_reject_duplicate_tax_id(db_session: Session) -> None:
    """El alta funciona y un ``tax_id`` repetido responde 409."""
    created = create_supplier(db_session, supplier_payload())
    assert created.id is not None
    assert created.payment_terms_days == 30
    assert created.is_active is True

    with pytest.raises(DuplicateResourceError) as exc:
        create_supplier(db_session, supplier_payload(company_name="Otro proveedor"))
    assert exc.value.status_code == 409
    assert "800987654-3" in str(exc.value)


def test_get_missing_supplier_returns_404(db_session: Session) -> None:
    """Consultar un proveedor inexistente responde 404."""
    from src.modules.purchasing.services import get_supplier

    with pytest.raises(ResourceNotFoundError) as exc:
        get_supplier(db_session, 999)
    assert exc.value.status_code == 404


def test_update_and_deactivate_supplier(
    db_session: Session, supplier: Supplier
) -> None:
    """PATCH parcial y borrado lógico conservan el historial."""
    updated = update_supplier(
        db_session,
        supplier.id,
        SupplierUpdate(payment_terms_days=60, phone="3005550100"),
    )
    assert updated.payment_terms_days == 60
    assert updated.company_name == supplier.company_name

    with pytest.raises(DuplicateResourceError):
        other = create_supplier(
            db_session, supplier_payload(tax_id="900111222-3")
        )
        update_supplier(
            db_session, other.id, SupplierUpdate(tax_id=supplier.tax_id)
        )

    deactivated = deactivate_supplier(db_session, supplier.id)
    assert deactivated.is_active is False
    assert list_suppliers(db_session, is_active=False)[0].id == supplier.id

    # Reactivar para corregir datos sigue siendo posible.
    reactivated = update_supplier(
        db_session, supplier.id, SupplierUpdate(is_active=True)
    )
    assert reactivated.is_active is True


# --------------------------------------------------------------------------- #
# Órdenes de compra
# --------------------------------------------------------------------------- #


def test_create_purchase_order_generates_sequential_codes_and_totals(
    db_session: Session, supplier: Supplier, product: Product
) -> None:
    """Los códigos son secuenciales por año y los totales se calculan."""
    first = create_purchase_order(
        db_session, order_payload(supplier.id, product.id)
    )
    second = create_purchase_order(
        db_session, order_payload(supplier.id, product.id)
    )

    prefix = f"OC-{_TODAY.year}-"
    assert first.code == f"{prefix}0001"
    assert second.code == f"{prefix}0002"
    assert first.status is PurchaseOrderStatus.DRAFT
    assert first.subtotal == Decimal("3750.00")
    assert first.tax_amount == Decimal("712.50")
    assert first.total == Decimal("4462.50")
    assert len(first.items) == 1
    assert first.items[0].subtotal == Decimal("3750.00")


def test_create_purchase_order_rejects_duplicate_explicit_code(
    db_session: Session, supplier: Supplier, product: Product
) -> None:
    """Un código explícito repetido responde 409."""
    payload = dict(code="OC-MANUAL-0001")
    create_purchase_order(db_session, order_payload(supplier.id, product.id, **payload))
    with pytest.raises(DuplicateResourceError) as exc:
        create_purchase_order(
            db_session, order_payload(supplier.id, product.id, **payload)
        )
    assert exc.value.status_code == 409


def test_inactive_supplier_cannot_receive_orders(
    db_session: Session, supplier: Supplier, product: Product
) -> None:
    """Escenario 2: emitir una OC a un proveedor inactivo responde 400."""
    deactivate_supplier(db_session, supplier.id)

    with pytest.raises(InactiveSupplierError) as exc:
        create_purchase_order(db_session, order_payload(supplier.id, product.id))
    assert exc.value.status_code == 400
    assert db_session.scalars(select(PurchaseOrder.id)).all() == []


def test_inactive_product_is_rejected_in_order_lines(
    db_session: Session, supplier: Supplier, product: Product
) -> None:
    """Escenario 7: una línea con producto inactivo responde 400."""
    product.is_active = False
    db_session.commit()

    with pytest.raises(InactiveProductError) as exc:
        create_purchase_order(db_session, order_payload(supplier.id, product.id))
    assert exc.value.status_code == 400
    assert "inactivo" in str(exc.value)
    assert db_session.scalars(select(PurchaseOrder.id)).all() == []


def test_missing_product_returns_404(
    db_session: Session, supplier: Supplier
) -> None:
    """Una línea con producto inexistente responde 404."""
    with pytest.raises(ResourceNotFoundError) as exc:
        create_purchase_order(db_session, order_payload(supplier.id, 9999))
    assert exc.value.status_code == 404


def test_update_draft_recalculates_totals_and_validates_products(
    db_session: Session, supplier: Supplier, product: Product
) -> None:
    """Editar el borrador reemplaza líneas y recalcula importes."""
    order = create_purchase_order(
        db_session, order_payload(supplier.id, product.id)
    )
    updated = update_purchase_order(
        db_session,
        order.id,
        PurchaseOrderUpdate(
            items=[
                PurchaseOrderItemCreate(
                    product_id=product.id,
                    quantity=10,
                    unit_price=Decimal("100.00"),
                    tax_rate=Decimal("0.00"),
                )
            ]
        ),
    )
    assert updated.subtotal == Decimal("1000.00")
    assert updated.tax_amount == Decimal("0.00")
    assert updated.total == Decimal("1000.00")
    assert len(updated.items) == 1
    assert updated.items[0].quantity == 10

    product.is_active = False
    db_session.commit()
    with pytest.raises(InactiveProductError):
        update_purchase_order(
            db_session,
            order.id,
            PurchaseOrderUpdate(
                items=[
                    PurchaseOrderItemCreate(
                        product_id=product.id,
                        quantity=1,
                        unit_price=Decimal("100.00"),
                    )
                ]
            ),
        )
    assert (product.is_active, order.status) == (False, PurchaseOrderStatus.DRAFT)


def test_non_draft_order_cannot_be_edited(
    db_session: Session, supplier: Supplier, product: Product
) -> None:
    """Una OC enviada/aprobada no puede editarse (409)."""
    order = create_purchase_order(
        db_session, order_payload(supplier.id, product.id)
    )
    order.status = PurchaseOrderStatus.APPROVED
    db_session.commit()

    with pytest.raises(InvalidOrderStateError) as exc:
        update_purchase_order(
            db_session, order.id, PurchaseOrderUpdate(supplier_id=supplier.id)
        )
    assert exc.value.status_code == 409

    # La orden se recupera con sus líneas para el futuro flujo de recepciones.
    assert get_purchase_order(db_session, order.id).items[0].product_id == product.id


# --------------------------------------------------------------------------- #
# Recepción de mercancía
# --------------------------------------------------------------------------- #


def test_goods_receipt_completes_order_and_increases_stock(
    db_session: Session, supplier: Supplier, product: Product, warehouse: Warehouse
) -> None:
    """Escenario 1: recibir todo impacta stock, acumulado y estado en un commit."""
    order = create_purchase_order(
        db_session, order_payload(supplier.id, product.id, quantity=50)
    )
    order.status = PurchaseOrderStatus.APPROVED
    db_session.commit()

    receipt = create_goods_receipt(
        db_session, receipt_payload(order, warehouse.id, quantity=50)
    )

    assert receipt.code == f"REC-{_TODAY.year}-0001"
    assert receipt.purchase_order_id == order.id
    assert receipt.warehouse_id == warehouse.id
    assert receipt.received_by == "almacenista-1"

    stored_order = get_purchase_order(db_session, order.id)
    assert stored_order.status is PurchaseOrderStatus.COMPLETED
    assert stored_order.items[0].received_quantity == 50

    stock = db_session.scalars(
        select(Stock).where(
            Stock.product_id == product.id, Stock.warehouse_id == warehouse.id
        )
    ).one()
    assert stock.quantity == 50

    movements = db_session.scalars(select(StockMovement)).all()
    assert len(movements) == 1
    movement = movements[0]
    assert movement.movement_type is MovementType.INBOUND
    assert movement.product_id == product.id
    assert movement.warehouse_source_id is None
    assert movement.warehouse_destination_id == warehouse.id
    assert movement.quantity == 50
    assert movement.reference_document == receipt.code
    assert movement.created_by == "almacenista-1"

    assert get_goods_receipt(db_session, receipt.id).items[0].quantity == 50
    assert list_goods_receipts(db_session, purchase_order_id=order.id) == [receipt]


def test_partial_receipts_accumulate_and_close_order(
    db_session: Session,
    approved_order: PurchaseOrder,
    product: Product,
    warehouse: Warehouse,
) -> None:
    """La recepción parcial acumula cantidades y la última cierra la OC."""
    first = create_goods_receipt(
        db_session, receipt_payload(approved_order, warehouse.id, quantity=8)
    )
    assert first.code == f"REC-{_TODAY.year}-0001"
    assert get_purchase_order(db_session, approved_order.id).status is (
        PurchaseOrderStatus.PARTIALLY_RECEIVED
    )
    partial_order = get_purchase_order(db_session, approved_order.id)
    assert partial_order.items[0].received_quantity == 8

    second = create_goods_receipt(
        db_session, receipt_payload(approved_order, warehouse.id, quantity=12)
    )
    assert second.code == f"REC-{_TODAY.year}-0002"

    final_order = get_purchase_order(db_session, approved_order.id)
    assert final_order.status is PurchaseOrderStatus.COMPLETED
    assert final_order.items[0].received_quantity == 20

    stock = db_session.scalars(
        select(Stock).where(
            Stock.product_id == product.id, Stock.warehouse_id == warehouse.id
        )
    ).one()
    assert stock.quantity == 20
    assert len(db_session.scalars(select(StockMovement)).all()) == 2
    assert len(list_goods_receipts(db_session, warehouse_id=warehouse.id)) == 2


def test_over_receipt_is_rejected_atomically(
    db_session: Session,
    approved_order: PurchaseOrder,
    warehouse: Warehouse,
) -> None:
    """Escenario 4: 25 > 20 pendientes responde 400 sin escribir nada."""
    with pytest.raises(OverReceiptError) as exc:
        create_goods_receipt(
            db_session, receipt_payload(approved_order, warehouse.id, quantity=25)
        )

    assert exc.value.status_code == 400
    assert exc.value.pending == 20
    assert exc.value.requested == 25
    assert "pendientes" in str(exc.value)

    assert db_session.scalars(select(GoodsReceipt.id)).all() == []
    assert db_session.scalars(select(GoodsReceiptItem.id)).all() == []
    assert db_session.scalars(select(StockMovement.id)).all() == []
    assert db_session.scalars(select(Stock.id)).all() == []
    untouched = get_purchase_order(db_session, approved_order.id)
    assert untouched.status is PurchaseOrderStatus.APPROVED
    assert untouched.items[0].received_quantity == 0


def test_receipt_requires_receivable_order_state(
    db_session: Session,
    supplier: Supplier,
    product: Product,
    warehouse: Warehouse,
    approved_order: PurchaseOrder,
) -> None:
    """Solo APPROVED/PARTIALLY_RECEIVED admiten recepciones (409 si no)."""
    draft = create_purchase_order(
        db_session, order_payload(supplier.id, product.id, quantity=2)
    )
    with pytest.raises(InvalidOrderStateError) as exc:
        create_goods_receipt(
            db_session, receipt_payload(draft, warehouse.id, quantity=1)
        )
    assert exc.value.status_code == 409

    create_goods_receipt(
        db_session, receipt_payload(approved_order, warehouse.id, quantity=20)
    )
    with pytest.raises(InvalidOrderStateError):
        create_goods_receipt(
            db_session, receipt_payload(approved_order, warehouse.id, quantity=1)
        )
    assert db_session.scalars(select(GoodsReceipt.id)).all() != []


def test_inactive_supplier_cannot_receive_goods(
    db_session: Session,
    supplier: Supplier,
    approved_order: PurchaseOrder,
    warehouse: Warehouse,
) -> None:
    """Una OC aprobada tampoco se recibe si el proveedor se desactivó."""
    deactivate_supplier(db_session, supplier.id)

    with pytest.raises(InactiveSupplierError) as exc:
        create_goods_receipt(
            db_session, receipt_payload(approved_order, warehouse.id, quantity=1)
        )
    assert exc.value.status_code == 400
    assert db_session.scalars(select(GoodsReceipt.id)).all() == []
    assert db_session.scalars(select(StockMovement.id)).all() == []


def test_receipts_are_immutable(
    db_session: Session,
    approved_order: PurchaseOrder,
    warehouse: Warehouse,
) -> None:
    """Escenario 6: ni la recepción ni sus líneas se editan o eliminan."""
    receipt = create_goods_receipt(
        db_session, receipt_payload(approved_order, warehouse.id, quantity=5)
    )
    db_session.expunge_all()
    stored = get_goods_receipt(db_session, receipt.id)
    movement_ids = db_session.scalars(select(StockMovement.id)).all()

    stored.notes = "Intento de modificación"
    with pytest.raises(ImmutableReceiptError) as exc:
        db_session.commit()
    assert exc.value.status_code == 400
    db_session.rollback()

    stored = get_goods_receipt(db_session, receipt.id)
    stored.items[0].quantity = 99
    with pytest.raises(ImmutableReceiptError):
        db_session.commit()
    db_session.rollback()

    stored = get_goods_receipt(db_session, receipt.id)
    db_session.delete(stored)
    with pytest.raises(ImmutableReceiptError):
        db_session.commit()
    db_session.rollback()

    final = get_goods_receipt(db_session, receipt.id)
    assert final.notes is None
    assert final.items[0].quantity == 5
    assert db_session.scalars(select(StockMovement.id)).all() == movement_ids
    assert get_purchase_order(db_session, approved_order.id).items[
        0
    ].received_quantity == 5


def test_duplicate_explicit_receipt_code_is_rejected(
    db_session: Session,
    approved_order: PurchaseOrder,
    warehouse: Warehouse,
) -> None:
    """Un código explícito repetido responde 409 sin duplicar la recepción."""
    payload = dict(code="REC-MANUAL-0001", quantity=1)
    create_goods_receipt(
        db_session, receipt_payload(approved_order, warehouse.id, **payload)
    )
    with pytest.raises(DuplicateResourceError) as exc:
        create_goods_receipt(
            db_session, receipt_payload(approved_order, warehouse.id, **payload)
        )
    assert exc.value.status_code == 409
    assert len(db_session.scalars(select(GoodsReceipt.id)).all()) == 1


def test_stock_movement_failure_rolls_back_whole_receipt(
    monkeypatch: pytest.MonkeyPatch,
    db_session: Session,
    supplier: Supplier,
    product: Product,
    warehouse: Warehouse,
) -> None:
    """Si inventory falla a mitad, se revierte receipt, acumulados y stock."""
    second_product = Product(
        sku="LAP-002",
        name="Laptop Segunda línea",
        unit_price=Decimal("900.00"),
        is_active=True,
    )
    db_session.add(second_product)
    db_session.commit()
    db_session.refresh(second_product)

    order = create_purchase_order(
        db_session,
        PurchaseOrderCreate(
            supplier_id=supplier.id,
            issue_date=_TODAY,
            expected_delivery_date=_TODAY + timedelta(days=10),
            items=[
                PurchaseOrderItemCreate(
                    product_id=product.id,
                    quantity=2,
                    unit_price=Decimal("1250.00"),
                ),
                PurchaseOrderItemCreate(
                    product_id=second_product.id,
                    quantity=2,
                    unit_price=Decimal("900.00"),
                ),
            ],
        ),
    )
    order.status = PurchaseOrderStatus.APPROVED
    db_session.commit()

    original = inventory_services.create_stock_movement
    calls = 0

    def failing_movement(db, data, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("fallo simulado en inventory")
        return original(db, data, **kwargs)

    monkeypatch.setattr(inventory_services, "create_stock_movement", failing_movement)

    both_lines = [
        GoodsReceiptItemCreate(purchase_order_item_id=line.id, quantity=2)
        for line in order.items
    ]
    with pytest.raises(RuntimeError, match="fallo simulado"):
        create_goods_receipt(
            db_session, receipt_payload(order, warehouse.id, items=both_lines)
        )

    assert calls == 2
    assert db_session.scalars(select(GoodsReceipt.id)).all() == []
    assert db_session.scalars(select(GoodsReceiptItem.id)).all() == []
    assert db_session.scalars(select(StockMovement.id)).all() == []
    assert db_session.scalars(select(Stock.id)).all() == []
    rolled_back = get_purchase_order(db_session, order.id)
    assert rolled_back.status is PurchaseOrderStatus.APPROVED
    assert [line.received_quantity for line in rolled_back.items] == [0, 0]


# --------------------------------------------------------------------------- #
# Cuentas por pagar
# --------------------------------------------------------------------------- #


def _billed_order(
    db_session: Session,
    supplier: Supplier,
    product: Product,
    warehouse: Warehouse,
    *,
    quantity: int = 20,
) -> tuple[PurchaseOrder, object]:
    """Crea una OC aprobada totalmente recibida y devuelve OC y recepción."""
    order = create_purchase_order(
        db_session, order_payload(supplier.id, product.id, quantity=quantity)
    )
    approve_purchase_order(db_session, order.id)
    receipt = create_goods_receipt(
        db_session, receipt_payload(order, warehouse.id, quantity=quantity)
    )
    return order, receipt


def test_supplier_bill_matches_receipt_and_calculates_due_date(
    db_session: Session, supplier: Supplier, product: Product, warehouse: Warehouse
) -> None:
    """La factura se valora con costos de la OC y cantidades recibidas."""
    order, receipt = _billed_order(db_session, supplier, product, warehouse)

    bill = create_supplier_bill(
        db_session,
        bill_payload(
            supplier.id,
            purchase_order_id=order.id,
            goods_receipt_id=receipt.id,  # type: ignore[arg-type]
        ),
    )

    assert bill.code == f"BILL-{_TODAY.year}-0001"
    assert bill.status is SupplierBillStatus.PENDING
    assert bill.purchase_order_id == order.id
    assert bill.goods_receipt_id == receipt.id  # type: ignore[union-attr]
    assert bill.subtotal == Decimal("25000.00")
    assert bill.tax_amount == Decimal("4750.00")
    assert bill.total == Decimal("29750.00")
    assert bill.balance_due == Decimal("29750.00")
    assert bill.due_date == _TODAY + timedelta(days=30)
    assert list_supplier_bills(db_session, status=SupplierBillStatus.PENDING) == [bill]


def test_supplier_bill_rejects_amount_mismatch(
    db_session: Session, supplier: Supplier, product: Product, warehouse: Warehouse
) -> None:
    """Facturar por encima de lo recibido o con otra tasa responde 400."""
    order, receipt = _billed_order(db_session, supplier, product, warehouse)
    source = dict(
        purchase_order_id=order.id,
        goods_receipt_id=receipt.id,  # type: ignore[arg-type]
    )

    with pytest.raises(InvalidBillError) as exc:
        create_supplier_bill(
            db_session,
            bill_payload(
                supplier.id,
                subtotal=Decimal("26000.00"),
                tax_amount=Decimal("4940.00"),
                **source,
            ),
        )
    assert exc.value.status_code == 400
    assert "excede lo pendiente" in str(exc.value)

    with pytest.raises(InvalidBillError) as tax_exc:
        create_supplier_bill(
            db_session,
            bill_payload(
                supplier.id,
                subtotal=Decimal("25000.00"),
                tax_amount=Decimal("1000.00"),
                supplier_invoice_number="F-2026-0043",
                **source,
            ),
        )
    assert "tasa pactada" in str(tax_exc.value)
    assert db_session.scalars(select(SupplierBill.id)).all() == []


def test_supplier_bill_requires_received_quantities(
    db_session: Session, supplier: Supplier, product: Product
) -> None:
    """No se puede facturar una OC sin movimientos de inventario."""
    order = create_purchase_order(
        db_session, order_payload(supplier.id, product.id, quantity=20)
    )
    approve_purchase_order(db_session, order.id)

    with pytest.raises(InvalidBillError) as exc:
        create_supplier_bill(
            db_session,
            bill_payload(supplier.id, purchase_order_id=order.id),
        )
    assert exc.value.status_code == 400
    assert "cantidades recibidas" in str(exc.value)


def test_partial_bills_cannot_exceed_received_total(
    db_session: Session, supplier: Supplier, product: Product, warehouse: Warehouse
) -> None:
    """Varios abonos facturables pueden repartir lo recibido, sin excederlo."""
    order, receipt = _billed_order(db_session, supplier, product, warehouse)
    source = dict(
        purchase_order_id=order.id,
        goods_receipt_id=receipt.id,  # type: ignore[arg-type]
    )

    first = create_supplier_bill(
        db_session,
        bill_payload(
            supplier.id,
            subtotal=Decimal("12500.00"),
            tax_amount=Decimal("2375.00"),
            supplier_invoice_number="F-2026-0001",
            **source,
        ),
    )
    second = create_supplier_bill(
        db_session,
        bill_payload(
            supplier.id,
            subtotal=Decimal("12500.00"),
            tax_amount=Decimal("2375.00"),
            supplier_invoice_number="F-2026-0002",
            **source,
        ),
    )
    assert first.code.endswith("0001")
    assert second.code.endswith("0002")

    with pytest.raises(InvalidBillError) as exc:
        create_supplier_bill(
            db_session,
            bill_payload(
                supplier.id,
                subtotal=Decimal("100.00"),
                tax_amount=Decimal("19.00"),
                supplier_invoice_number="F-2026-0003",
                **source,
            ),
        )
    assert "excede lo pendiente" in str(exc.value)
    assert len(db_session.scalars(select(SupplierBill.id)).all()) == 2


def test_bill_payment_history_and_status(
    db_session: Session, supplier: Supplier, product: Product, warehouse: Warehouse
) -> None:
    """Los abonos actualizan el saldo y dejan historial inmutable."""
    order, receipt = _billed_order(db_session, supplier, product, warehouse)
    bill = create_supplier_bill(
        db_session,
        bill_payload(
            supplier.id,
            purchase_order_id=order.id,
            goods_receipt_id=receipt.id,  # type: ignore[arg-type]
        ),
    )

    with pytest.raises(InvalidBillError) as exc:
        register_bill_payment(
            db_session,
            bill.id,
            SupplierBillPaymentCreate(amount=Decimal("29750.01")),
        )
    assert exc.value.status_code == 400
    assert db_session.scalars(select(SupplierBillPayment.id)).all() == []

    partial = register_bill_payment(
        db_session,
        bill.id,
        SupplierBillPaymentCreate(amount=Decimal("10000.00"), reference="TRANS-1"),
    )
    assert partial.status is SupplierBillStatus.PARTIALLY_PAID
    assert partial.balance_due == Decimal("19750.00")

    paid = register_bill_payment(
        db_session,
        bill.id,
        SupplierBillPaymentCreate(amount=Decimal("19750.00")),
    )
    assert paid.status is SupplierBillStatus.PAID
    assert paid.balance_due == Decimal("0.00")

    with pytest.raises(InvalidBillStateError) as state_exc:
        register_bill_payment(
            db_session,
            bill.id,
            SupplierBillPaymentCreate(amount=Decimal("1.00")),
        )
    assert state_exc.value.status_code == 409

    payments = list_bill_payments(db_session, bill_id=bill.id)
    assert [payment.amount for payment in payments] == [
        Decimal("10000.00"),
        Decimal("19750.00"),
    ]
    assert payments[0].reference == "TRANS-1"


def test_financial_documents_are_immutable(
    db_session: Session, supplier: Supplier, product: Product, warehouse: Warehouse
) -> None:
    """Ni facturas ni abonos se editan o eliminan; solo contrapartidas."""
    order, receipt = _billed_order(db_session, supplier, product, warehouse)
    bill = create_supplier_bill(
        db_session,
        bill_payload(
            supplier.id,
            purchase_order_id=order.id,
            goods_receipt_id=receipt.id,  # type: ignore[arg-type]
        ),
    )
    register_bill_payment(
        db_session, bill.id, SupplierBillPaymentCreate(amount=Decimal("1000.00"))
    )
    db_session.expunge_all()

    stored = get_supplier_bill(db_session, bill.id)
    stored.subtotal = Decimal("1.00")
    with pytest.raises(ImmutableBillError) as exc:
        db_session.commit()
    assert exc.value.status_code == 400
    db_session.rollback()

    stored = get_supplier_bill(db_session, bill.id)
    stored.issue_date = _TODAY + timedelta(days=1)
    with pytest.raises(ImmutableBillError):
        db_session.commit()
    db_session.rollback()

    stored = get_supplier_bill(db_session, bill.id)
    db_session.delete(stored)
    with pytest.raises(ImmutableBillError):
        db_session.commit()
    db_session.rollback()

    payment = db_session.scalars(select(SupplierBillPayment)).one()
    payment.amount = Decimal("1.00")
    with pytest.raises(ImmutableBillError):
        db_session.commit()
    db_session.rollback()

    payment = db_session.scalars(select(SupplierBillPayment)).one()
    db_session.delete(payment)
    with pytest.raises(ImmutableBillError):
        db_session.commit()
    db_session.rollback()

    final = get_supplier_bill(db_session, bill.id)
    assert final.subtotal == Decimal("25000.00")
    assert final.issue_date == _TODAY
    assert final.balance_due == Decimal("28750.00")
    assert len(list_bill_payments(db_session, bill_id=bill.id)) == 1

    with pytest.raises(ImmutableBillError):
        reject_bill_mutation(db_session, bill.id)


def test_void_supplier_bill_and_duplicate_invoice_number(
    db_session: Session, supplier: Supplier, product: Product, warehouse: Warehouse
) -> None:
    """VOID solo entre facturas sin pagos; el número físico es único."""
    order, receipt = _billed_order(db_session, supplier, product, warehouse)
    source = dict(
        purchase_order_id=order.id,
        goods_receipt_id=receipt.id,  # type: ignore[arg-type]
    )
    partial = dict(subtotal=Decimal("12500.00"), tax_amount=Decimal("2375.00"))
    bill = create_supplier_bill(db_session, bill_payload(supplier.id, **partial, **source))

    with pytest.raises(DuplicateResourceError) as exc:
        create_supplier_bill(db_session, bill_payload(supplier.id, **partial, **source))
    assert exc.value.status_code == 409

    unpaid = create_supplier_bill(
        db_session,
        bill_payload(
            supplier.id,
            supplier_invoice_number="F-2026-0099",
            **partial,
            **source,
        ),
    )
    voided = void_supplier_bill(db_session, unpaid.id)
    assert voided.status is SupplierBillStatus.VOID
    assert voided.balance_due == Decimal("0.00")
    assert void_supplier_bill(db_session, unpaid.id).status is SupplierBillStatus.VOID

    register_bill_payment(
        db_session, bill.id, SupplierBillPaymentCreate(amount=Decimal("100.00"))
    )
    with pytest.raises(InvalidBillStateError):
        void_supplier_bill(db_session, bill.id)


def test_order_approve_cancel_and_force_close(
    db_session: Session, supplier: Supplier, product: Product, warehouse: Warehouse
) -> None:
    """Transiciones de OC y bloqueo de cancelación con recepciones."""
    order = create_purchase_order(
        db_session, order_payload(supplier.id, product.id, quantity=2)
    )
    approved = approve_purchase_order(db_session, order.id)
    assert approved.status is PurchaseOrderStatus.APPROVED

    sent_order = create_purchase_order(
        db_session, order_payload(supplier.id, product.id, quantity=2)
    )
    sent = approve_purchase_order(db_session, sent_order.id, send=True)
    assert sent.status is PurchaseOrderStatus.SENT
    assert cancel_purchase_order(db_session, sent.id).status is (
        PurchaseOrderStatus.CANCELLED
    )

    create_goods_receipt(
        db_session, receipt_payload(approved, warehouse.id, quantity=1)
    )
    with pytest.raises(InvalidOrderDataError) as exc:
        cancel_purchase_order(db_session, approved.id)
    assert exc.value.status_code == 400
    assert "movimientos de inventario" in str(exc.value)

    closed = force_close_purchase_order(db_session, approved.id)
    assert closed.status is PurchaseOrderStatus.FORCE_CLOSED


# --------------------------------------------------------------------------- #
# Escenarios críticos por HTTP (router + RBAC)
# --------------------------------------------------------------------------- #

_API_URL = "/api/v1/purchasing"
_INVENTORY_API_URL = "/api/v1/inventory"
_API_HASHED_PASSWORD = hash_password("Purchasing1234!")


@pytest.fixture()
def api_engine() -> Generator[Engine, None, None]:
    """Engine SQLite con el mismo tratamiento de ``BEGIN`` que en producción.

    El driver ``pysqlite`` no emite ``BEGIN`` antes de un ``SAVEPOINT``; se
    desactiva su transacción implícita para que los rollback atómicos se
    comporten como en PostgreSQL.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _disable_implicit_begin(
        dbapi_connection: Any, _connection_record: Any
    ) -> None:
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _emit_begin(connection: Any) -> None:
        connection.exec_driver_sql("BEGIN")

    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture()
def api_session(api_engine: Engine) -> Generator[Session, None, None]:
    """Sesión compartida entre la API y las aserciones de cada prueba HTTP."""
    factory = sessionmaker(bind=api_engine, expire_on_commit=False)
    with factory() as session:
        yield session


@pytest.fixture()
def client(api_session: Session) -> Generator[TestClient, None, None]:
    """Cliente HTTP con ``get_db`` sustituido por la sesión de prueba."""

    def override_get_db() -> Generator[Session, None, None]:
        yield api_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)


def _api_role(session: Session, name: RoleEnum, modules: list[str]) -> Role:
    """Obtiene o crea un rol de forma idempotente."""
    role = session.scalar(select(Role).where(Role.name == name))
    if role is None:
        role = Role(name=name, description=name.value, allowed_modules=modules)
        session.add(role)
        session.flush()
    return role


def _api_user(
    session: Session, *, role: Role, username: str, email: str
) -> User:
    """Crea un usuario activo con el rol indicado."""
    user = User(
        email=email,
        username=username,
        full_name=username.title(),
        hashed_password=_API_HASHED_PASSWORD,
        role_id=role.id,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


@pytest.fixture()
def api_accounts(api_session: Session) -> dict[str, User]:
    """Usuarios con roles ``ADMINISTRATOR``, ``PURCHASING`` e ``INVENTORY``."""
    admin = _api_role(api_session, RoleEnum.ADMINISTRATOR, ["*"])
    purchasing = _api_role(
        api_session, RoleEnum.PURCHASING, ["purchasing", "inventory:read"]
    )
    inventory = _api_role(api_session, RoleEnum.INVENTORY, ["inventory"])
    api_session.commit()
    return {
        "admin": _api_user(
            api_session,
            role=admin,
            username="admin_compras",
            email="admin-compras@example.com",
        ),
        "purchasing": _api_user(
            api_session,
            role=purchasing,
            username="comprador",
            email="comprador@example.com",
        ),
        "inventory": _api_user(
            api_session,
            role=inventory,
            username="bodeguero",
            email="bodeguero@example.com",
        ),
    }


def _api_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.fixture()
def admin_headers(api_accounts: dict[str, User]) -> dict[str, str]:
    return _api_headers(api_accounts["admin"])


@pytest.fixture()
def purchasing_headers(api_accounts: dict[str, User]) -> dict[str, str]:
    return _api_headers(api_accounts["purchasing"])


@pytest.fixture()
def inventory_headers(api_accounts: dict[str, User]) -> dict[str, str]:
    return _api_headers(api_accounts["inventory"])


def _api_catalog(
    client: TestClient, admin_headers: dict[str, str]
) -> dict[str, int]:
    """Crea una bodega y un producto vía API (requiere rol de inventario)."""
    warehouse = client.post(
        f"{_INVENTORY_API_URL}/warehouses",
        headers=admin_headers,
        json={"code": "BOD-PRINCIPAL", "name": "Bodega Principal"},
    )
    assert warehouse.status_code == 201, warehouse.text
    product = client.post(
        f"{_INVENTORY_API_URL}/products",
        headers=admin_headers,
        json={
            "sku": "LAP-001",
            "name": "Laptop Industrial",
            "unit_price": "1250.00",
            "minimum_stock": 1,
        },
    )
    assert product.status_code == 201, product.text
    return {
        "warehouse_id": warehouse.json()["id"],
        "product_id": product.json()["id"],
    }


def _api_supplier(
    client: TestClient, headers: dict[str, str], *, tax_id: str = "800987654-3"
) -> dict[str, Any]:
    """Registra un proveedor vía API y devuelve su representación."""
    response = client.post(
        f"{_API_URL}/suppliers",
        headers=headers,
        json={
            "tax_id": tax_id,
            "company_name": "Proveedores del Norte S.A.S.",
            "contact_name": "María Gómez",
            "email": "ventas@proveedoresnorte.com",
            "address": "Calle 10 # 20-30",
            "payment_terms_days": 30,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _api_order(
    client: TestClient,
    headers: dict[str, str],
    supplier_id: int,
    product_id: int,
    *,
    quantity: int,
) -> dict[str, Any]:
    """Crea una OC en borrador vía API."""
    response = client.post(
        f"{_API_URL}/orders",
        headers=headers,
        json={
            "supplier_id": supplier_id,
            "expected_delivery_date": str(_TODAY + timedelta(days=10)),
            "items": [
                {
                    "product_id": product_id,
                    "quantity": quantity,
                    "unit_price": "1250.00",
                    "tax_rate": "19.00",
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _api_approve(
    client: TestClient, headers: dict[str, str], order_id: int
) -> None:
    """Aprueba una OC vía API."""
    response = client.post(
        f"{_API_URL}/orders/{order_id}/approve", headers=headers
    )
    assert response.status_code == 200, response.text


def _api_receipt(
    client: TestClient,
    headers: dict[str, str],
    order: dict[str, Any],
    warehouse_id: int,
    *,
    quantity: int,
) -> Any:  # noqa: ANN401 - respuesta HTTP sin tipo específico
    """Intenta registrar una recepción y devuelve la respuesta sin asumir éxito."""
    return client.post(
        f"{_API_URL}/receipts",
        headers=headers,
        json={
            "purchase_order_id": order["id"],
            "warehouse_id": warehouse_id,
            "items": [
                {
                    "purchase_order_item_id": order["items"][0]["id"],
                    "quantity": quantity,
                }
            ],
        },
    )


def test_http_supplier_created_duplicate_tax_id_and_inactive_supplier(
    client: TestClient,
    api_session: Session,
    purchasing_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> None:
    """Escenario 1/3: alta de proveedor, NIT duplicado y proveedor inactivo.

    El ``tax_id`` duplicado se rechaza con 409 (la spec admite 400/422) y una
    OC contra un proveedor desactivado con 400.
    """
    supplier = _api_supplier(client, purchasing_headers)

    duplicate = client.post(
        f"{_API_URL}/suppliers",
        headers=purchasing_headers,
        json={
            "tax_id": "800987654-3",
            "company_name": "Otro proveedor",
            "contact_name": "Carlos Pérez",
            "email": "otro@example.com",
            "address": "Calle 20 # 30-40",
        },
    )
    assert duplicate.status_code in {400, 409, 422}
    assert "800987654-3" in duplicate.text

    deactivate = client.patch(
        f"{_API_URL}/suppliers/{supplier['id']}",
        headers=purchasing_headers,
        json={"is_active": False},
    )
    assert deactivate.status_code == 200, deactivate.text
    assert deactivate.json()["is_active"] is False

    catalog = _api_catalog(client, admin_headers)
    order = client.post(
        f"{_API_URL}/orders",
        headers=purchasing_headers,
        json={
            "supplier_id": supplier["id"],
            "expected_delivery_date": str(_TODAY + timedelta(days=10)),
            "items": [
                {
                    "product_id": catalog["product_id"],
                    "quantity": 1,
                    "unit_price": "1250.00",
                }
            ],
        },
    )
    assert order.status_code == 400
    assert "activo" in order.text.lower()
    assert api_session.scalars(select(PurchaseOrder.id)).all() == []


def test_http_inactive_product_in_order_is_rejected(
    client: TestClient,
    api_session: Session,
    purchasing_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> None:
    """Escenario 7: incluir un producto inactivo en una OC responde 400."""
    catalog = _api_catalog(client, admin_headers)
    deactivate = client.patch(
        f"{_INVENTORY_API_URL}/products/{catalog['product_id']}",
        headers=admin_headers,
        json={"is_active": False},
    )
    assert deactivate.status_code == 200, deactivate.text

    supplier = _api_supplier(client, purchasing_headers)
    response = client.post(
        f"{_API_URL}/orders",
        headers=purchasing_headers,
        json={
            "supplier_id": supplier["id"],
            "expected_delivery_date": str(_TODAY + timedelta(days=10)),
            "items": [
                {
                    "product_id": catalog["product_id"],
                    "quantity": 5,
                    "unit_price": "1250.00",
                }
            ],
        },
    )
    assert response.status_code == 400
    assert "inactivo" in response.text.lower()
    assert api_session.scalars(select(PurchaseOrder.id)).all() == []


def test_http_goods_receipt_completes_order_and_increases_stock(
    client: TestClient,
    api_session: Session,
    purchasing_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> None:
    """Escenario 1: recibir 50 unidades impacta stock y cierra la OC."""
    catalog = _api_catalog(client, admin_headers)
    supplier = _api_supplier(client, purchasing_headers)
    order = _api_order(
        client,
        purchasing_headers,
        supplier["id"],
        catalog["product_id"],
        quantity=50,
    )
    _api_approve(client, purchasing_headers, order["id"])

    receipt = _api_receipt(
        client,
        purchasing_headers,
        order,
        catalog["warehouse_id"],
        quantity=50,
    )
    assert receipt.status_code == 201, receipt.text
    assert receipt.json()["code"].startswith(f"REC-{_TODAY.year}-")

    stored = client.get(
        f"{_API_URL}/orders/{order['id']}", headers=purchasing_headers
    )
    assert stored.status_code == 200
    assert stored.json()["status"] == PurchaseOrderStatus.COMPLETED.value
    assert stored.json()["items"][0]["received_quantity"] == 50

    stock = client.get(
        f"{_INVENTORY_API_URL}/stock",
        headers=purchasing_headers,
        params={
            "product_id": catalog["product_id"],
            "warehouse_id": catalog["warehouse_id"],
        },
    )
    assert stock.status_code == 200, stock.text
    assert stock.json()[0]["quantity"] == 50

    movements = api_session.scalars(select(StockMovement)).all()
    assert len(movements) == 1
    assert movements[0].movement_type is MovementType.INBOUND
    assert movements[0].quantity == 50
    assert movements[0].reference_document == receipt.json()["code"]


def test_http_over_receipt_is_rejected_atomically(
    client: TestClient,
    api_session: Session,
    purchasing_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> None:
    """Escenario 4: recibir 25 de 20 pendientes responde 400 sin escrituras."""
    catalog = _api_catalog(client, admin_headers)
    supplier = _api_supplier(client, purchasing_headers)
    order = _api_order(
        client,
        purchasing_headers,
        supplier["id"],
        catalog["product_id"],
        quantity=20,
    )
    _api_approve(client, purchasing_headers, order["id"])

    response = _api_receipt(
        client,
        purchasing_headers,
        order,
        catalog["warehouse_id"],
        quantity=25,
    )
    assert response.status_code == 400
    assert "pendientes" in response.text.lower()

    assert api_session.scalars(select(GoodsReceipt.id)).all() == []
    assert api_session.scalars(select(GoodsReceiptItem.id)).all() == []
    assert api_session.scalars(select(StockMovement.id)).all() == []
    assert api_session.scalars(select(Stock.id)).all() == []

    untouched = client.get(
        f"{_API_URL}/orders/{order['id']}", headers=purchasing_headers
    )
    assert untouched.json()["status"] == PurchaseOrderStatus.APPROVED.value
    assert untouched.json()["items"][0]["received_quantity"] == 0


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/suppliers"),
        ("POST", "/suppliers"),
        ("GET", "/orders"),
        ("POST", "/orders"),
        ("GET", "/receipts"),
        ("POST", "/receipts"),
        ("GET", "/bills"),
    ],
)
def test_http_rbac_rejects_role_without_purchasing(
    client: TestClient,
    inventory_headers: dict[str, str],
    method: str,
    path: str,
) -> None:
    """Escenario 5: un rol sin ``PURCHASING``/``ADMINISTRATOR`` recibe 403."""
    response = client.request(
        method, f"{_API_URL}{path}", headers=inventory_headers, json={}
    )
    assert response.status_code == 403


@pytest.mark.parametrize("headers_name", ["purchasing_headers", "admin_headers"])
def test_http_rbac_allows_authorized_roles(
    request: pytest.FixtureRequest,
    client: TestClient,
    headers_name: str,
) -> None:
    """Los roles ``PURCHASING`` y ``ADMINISTRATOR`` pueden operar (bypass)."""
    headers: dict[str, str] = request.getfixturevalue(headers_name)
    assert client.get(f"{_API_URL}/suppliers", headers=headers).status_code == 200
    assert client.get(f"{_API_URL}/orders", headers=headers).status_code == 200
    assert client.get(f"{_API_URL}/receipts", headers=headers).status_code == 200
    assert client.get(f"{_API_URL}/bills", headers=headers).status_code == 200


def test_http_rbac_rejects_anonymous_request(client: TestClient) -> None:
    """Sin token, el acceso responde 401 antes que 403."""
    response = client.get(f"{_API_URL}/suppliers")
    assert response.status_code == 401
