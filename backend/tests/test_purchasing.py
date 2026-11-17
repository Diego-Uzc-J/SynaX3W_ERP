"""Pruebas de aceptación de la capa de servicios de ``purchasing``.

Cubren los escenarios 2, 3 y 7 de ``specs/purchasing_spec.md`` (proveedor
inactivo, ``tax_id`` duplicado y producto inactivo en una línea de OC), además
de la generación secuencial de códigos ``OC-YYYY-XXXX`` y el recálculo de
totales al editar un borrador.

Las pruebas son de servicio (sin router todavía) y usan SQLite en memoria; por
ello comprueban directamente el ``status_code`` de las excepciones HTTP de
dominio, que es el mismo que FastAPI devolverá al registrar el router.
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ["DATABASE_URL"] = "sqlite://"

from src.core.database import Base  # noqa: E402
from src.modules.inventory.models import Product  # noqa: E402
from src.modules.purchasing.models import (  # noqa: E402
    PurchaseOrder,
    PurchaseOrderStatus,
    Supplier,
)
from src.modules.purchasing.schemas import (  # noqa: E402
    PurchaseOrderCreate,
    PurchaseOrderItemCreate,
    PurchaseOrderUpdate,
    SupplierCreate,
    SupplierUpdate,
)
from src.modules.purchasing.services import (  # noqa: E402
    DuplicateResourceError,
    InactiveProductError,
    InactiveSupplierError,
    InvalidOrderStateError,
    ResourceNotFoundError,
    create_purchase_order,
    create_supplier,
    deactivate_supplier,
    get_purchase_order,
    list_suppliers,
    update_purchase_order,
    update_supplier,
)

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
    supplier_id: int, product_id: int, **overrides: object
) -> PurchaseOrderCreate:
    """Datos válidos para crear una OC de una línea."""
    values: dict[str, object] = {
        "supplier_id": supplier_id,
        "issue_date": _TODAY,
        "expected_delivery_date": _TODAY + timedelta(days=15),
        "items": [
            PurchaseOrderItemCreate(
                product_id=product_id,
                quantity=3,
                unit_price=Decimal("1250.00"),
                tax_rate=Decimal("19.00"),
            )
        ],
    }
    values.update(overrides)
    return PurchaseOrderCreate(**values)  # type: ignore[arg-type]


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


def test_update_and_deactivate_supplier(db_session: Session, supplier: Supplier) -> None:
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
