"""Routers FastAPI del módulo de Compras y Proveedores.

Expone los contratos de ``specs/purchasing_spec.md`` (sección 4) bajo el
prefijo ``/api/v1/purchasing``, aplicado al registrar este router en
``src.main``. Incluye proveedores, órdenes de compra, recepciones y cuentas por
pagar con su historial de abonos.

Todos los endpoints exigen un token válido con rol ``PURCHASING``; el rol
``ADMINISTRATOR`` pasa automáticamente por el *superuser bypass* de
``require_roles`` (``specs/users_spec.md``, sección 4.3). La matriz de permisos
del manifiesto concede además ``inventory:read`` a ``PURCHASING`` para consultar
el catálogo al que se vinculan las líneas y las recepciones.

``purchasing_exception_handler`` traduce las excepciones de dominio a HTTP
usando el ``status_code`` declarado por cada clase (400/404/409).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.security import require_roles
from src.modules.purchasing import services
from src.modules.purchasing.models import (
    PurchaseOrderStatus,
    SupplierBillStatus,
)
from src.modules.purchasing.schemas import (
    GoodsReceiptCreate,
    GoodsReceiptResponse,
    PurchaseOrderApproveRequest,
    PurchaseOrderCancelRequest,
    PurchaseOrderCreate,
    PurchaseOrderResponse,
    PurchaseOrderUpdate,
    SupplierBillCreate,
    SupplierBillPaymentCreate,
    SupplierBillPaymentResponse,
    SupplierBillResponse,
    SupplierCreate,
    SupplierResponse,
    SupplierUpdate,
)
from src.modules.purchasing.services import PurchasingServiceError
from src.modules.users.models import RoleEnum, User

__all__ = ["router", "purchasing_exception_handler"]


# --------------------------------------------------------------------------- #
# Guardia RBAC (spec de users, sección 4.3)
# --------------------------------------------------------------------------- #

#: ``ADMINISTRATOR`` pasa siempre gracias al bypass interno de ``require_roles``.
require_purchasing = require_roles([RoleEnum.PURCHASING])


async def purchasing_exception_handler(
    _request: Request, exc: PurchasingServiceError
) -> JSONResponse:
    """Convierte un error de dominio de compras en una respuesta HTTP."""
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


# --------------------------------------------------------------------------- #
# Proveedores — /api/v1/purchasing/suppliers
# --------------------------------------------------------------------------- #

suppliers_router = APIRouter(prefix="/suppliers", tags=["purchasing: suppliers"])


@suppliers_router.post(
    "",
    response_model=SupplierResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un proveedor",
    dependencies=[Depends(require_purchasing)],
)
def create_supplier(
    payload: SupplierCreate,
    db: Session = Depends(get_db),
) -> SupplierResponse:
    """Registra un proveedor validando la unicidad de su ``tax_id``."""
    supplier = services.create_supplier(db, payload)
    return SupplierResponse.model_validate(supplier)


@suppliers_router.get(
    "",
    response_model=list[SupplierResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar proveedores",
    dependencies=[Depends(require_purchasing)],
)
def list_suppliers(
    skip: int = Query(0, ge=0, description="Registros a omitir."),
    limit: int = Query(100, ge=1, le=200, description="Máximo de registros."),
    company_name: str | None = Query(None, description="Filtro por razón social."),
    tax_id: str | None = Query(None, description="Filtro por identificador fiscal."),
    is_active: bool | None = Query(None, description="Filtro por estado."),
    db: Session = Depends(get_db),
) -> list[SupplierResponse]:
    """Lista proveedores con filtros y paginación."""
    suppliers = services.list_suppliers(
        db,
        skip=skip,
        limit=limit,
        company_name=company_name,
        tax_id=tax_id,
        is_active=is_active,
    )
    return [SupplierResponse.model_validate(item) for item in suppliers]


@suppliers_router.get(
    "/{supplier_id}",
    response_model=SupplierResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener un proveedor",
    dependencies=[Depends(require_purchasing)],
)
def get_supplier(
    supplier_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> SupplierResponse:
    """Devuelve el detalle de un proveedor o 404 si no existe."""
    supplier = services.get_supplier(db, supplier_id)
    return SupplierResponse.model_validate(supplier)


@suppliers_router.patch(
    "/{supplier_id}",
    response_model=SupplierResponse,
    status_code=status.HTTP_200_OK,
    summary="Actualizar un proveedor",
    dependencies=[Depends(require_purchasing)],
)
def update_supplier(
    payload: SupplierUpdate,
    supplier_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> SupplierResponse:
    """Actualiza datos o plazos de pago; también permite reactivar."""
    supplier = services.update_supplier(db, supplier_id, payload)
    return SupplierResponse.model_validate(supplier)


# --------------------------------------------------------------------------- #
# Órdenes de compra — /api/v1/purchasing/orders
# --------------------------------------------------------------------------- #

orders_router = APIRouter(prefix="/orders", tags=["purchasing: orders"])


@orders_router.post(
    "",
    response_model=PurchaseOrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una orden de compra en borrador",
    dependencies=[Depends(require_purchasing)],
)
def create_purchase_order(
    payload: PurchaseOrderCreate,
    db: Session = Depends(get_db),
) -> PurchaseOrderResponse:
    """Crea la OC con totales calculados y proveedor/productos activos."""
    order = services.create_purchase_order(db, payload)
    return PurchaseOrderResponse.model_validate(order)


@orders_router.get(
    "",
    response_model=list[PurchaseOrderResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar órdenes de compra",
    dependencies=[Depends(require_purchasing)],
)
def list_purchase_orders(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    status_filter: PurchaseOrderStatus | None = Query(None, alias="status"),
    supplier_id: int | None = Query(None, gt=0),
    code: str | None = Query(None, description="Filtro parcial por código."),
    db: Session = Depends(get_db),
) -> list[PurchaseOrderResponse]:
    """Lista órdenes con filtros por estado, proveedor o código."""
    orders = services.list_purchase_orders(
        db,
        skip=skip,
        limit=limit,
        status=status_filter,
        supplier_id=supplier_id,
        code=code,
    )
    return [PurchaseOrderResponse.model_validate(order) for order in orders]


@orders_router.get(
    "/{order_id}",
    response_model=PurchaseOrderResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener una orden de compra",
    dependencies=[Depends(require_purchasing)],
)
def get_purchase_order(
    order_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> PurchaseOrderResponse:
    """Devuelve una OC con sus líneas o 404 si no existe."""
    order = services.get_purchase_order(db, order_id)
    return PurchaseOrderResponse.model_validate(order)


@orders_router.patch(
    "/{order_id}",
    response_model=PurchaseOrderResponse,
    status_code=status.HTTP_200_OK,
    summary="Editar una orden de compra en borrador",
    dependencies=[Depends(require_purchasing)],
)
def update_purchase_order(
    payload: PurchaseOrderUpdate,
    order_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> PurchaseOrderResponse:
    """Edita una OC solo mientras permanezca en ``DRAFT``."""
    order = services.update_purchase_order(db, order_id, payload)
    return PurchaseOrderResponse.model_validate(order)


@orders_router.post(
    "/{order_id}/approve",
    response_model=PurchaseOrderResponse,
    status_code=status.HTTP_200_OK,
    summary="Aprobar o enviar una orden de compra",
    dependencies=[Depends(require_purchasing)],
)
def approve_purchase_order(
    payload: PurchaseOrderApproveRequest | None = None,
    order_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> PurchaseOrderResponse:
    """Pasa la orden de ``DRAFT`` a ``APPROVED`` (o a ``SENT``)."""
    order = services.approve_purchase_order(db, order_id, send=bool(payload and payload.send))
    return PurchaseOrderResponse.model_validate(order)


@orders_router.post(
    "/{order_id}/cancel",
    response_model=PurchaseOrderResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancelar una orden de compra",
    dependencies=[Depends(require_purchasing)],
)
def cancel_purchase_order(
    payload: PurchaseOrderCancelRequest | None = None,
    order_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> PurchaseOrderResponse:
    """Cancela la OC salvo que ya tenga recepciones de inventario."""
    order = services.cancel_purchase_order(
        db, order_id, reason=payload.reason if payload else None
    )
    return PurchaseOrderResponse.model_validate(order)


@orders_router.post(
    "/{order_id}/force-close",
    response_model=PurchaseOrderResponse,
    status_code=status.HTTP_200_OK,
    summary="Cerrar forzosamente una orden de compra",
    dependencies=[Depends(require_purchasing)],
)
def force_close_purchase_order(
    order_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> PurchaseOrderResponse:
    """Libera saldos pendientes pasando la OC a ``FORCE_CLOSED``."""
    order = services.force_close_purchase_order(db, order_id)
    return PurchaseOrderResponse.model_validate(order)


# --------------------------------------------------------------------------- #
# Recepción de mercancía — /api/v1/purchasing/receipts
# --------------------------------------------------------------------------- #

receipts_router = APIRouter(prefix="/receipts", tags=["purchasing: receipts"])


@receipts_router.post(
    "",
    response_model=GoodsReceiptResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar una recepción de mercancía",
)
def create_goods_receipt(
    payload: GoodsReceiptCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_purchasing),
) -> GoodsReceiptResponse:
    """Recibe mercancía e impacta el stock en una sola transacción ACID.

    Si el cuerpo no indica ``received_by``, se usa el usuario autenticado como
    responsable de la recepción y de los movimientos de inventario.
    """
    if payload.received_by is None:
        payload = payload.model_copy(update={"received_by": current_user.username})
    receipt = services.create_goods_receipt(db, payload)
    return GoodsReceiptResponse.model_validate(receipt)


@receipts_router.get(
    "",
    response_model=list[GoodsReceiptResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar recepciones",
    dependencies=[Depends(require_purchasing)],
)
def list_goods_receipts(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    purchase_order_id: int | None = Query(None, gt=0),
    warehouse_id: int | None = Query(None, gt=0),
    db: Session = Depends(get_db),
) -> list[GoodsReceiptResponse]:
    """Lista el historial de recepciones con filtros por OC o bodega."""
    receipts = services.list_goods_receipts(
        db,
        skip=skip,
        limit=limit,
        purchase_order_id=purchase_order_id,
        warehouse_id=warehouse_id,
    )
    return [GoodsReceiptResponse.model_validate(item) for item in receipts]


@receipts_router.get(
    "/{receipt_id}",
    response_model=GoodsReceiptResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener una recepción",
    dependencies=[Depends(require_purchasing)],
)
def get_goods_receipt(
    receipt_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> GoodsReceiptResponse:
    """Devuelve una recepción con sus líneas o 404 si no existe."""
    receipt = services.get_goods_receipt(db, receipt_id)
    return GoodsReceiptResponse.model_validate(receipt)


# --------------------------------------------------------------------------- #
# Cuentas por pagar — /api/v1/purchasing/bills
# --------------------------------------------------------------------------- #

bills_router = APIRouter(prefix="/bills", tags=["purchasing: bills"])


@bills_router.post(
    "",
    response_model=SupplierBillResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar una factura de proveedor",
    dependencies=[Depends(require_purchasing)],
)
def create_supplier_bill(
    payload: SupplierBillCreate,
    db: Session = Depends(get_db),
) -> SupplierBillResponse:
    """Valora la factura contra costos pactados y cantidades recibidas."""
    bill = services.create_supplier_bill(db, payload)
    return SupplierBillResponse.model_validate(bill)


@bills_router.get(
    "",
    response_model=list[SupplierBillResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar facturas de proveedor",
    dependencies=[Depends(require_purchasing)],
)
def list_supplier_bills(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    status_filter: SupplierBillStatus | None = Query(None, alias="status"),
    supplier_id: int | None = Query(None, gt=0),
    purchase_order_id: int | None = Query(None, gt=0),
    goods_receipt_id: int | None = Query(None, gt=0),
    code: str | None = Query(None, description="Filtro parcial por código."),
    db: Session = Depends(get_db),
) -> list[SupplierBillResponse]:
    """Lista cuentas por pagar con filtros por estado y documento origen."""
    bills = services.list_supplier_bills(
        db,
        skip=skip,
        limit=limit,
        status=status_filter,
        supplier_id=supplier_id,
        purchase_order_id=purchase_order_id,
        goods_receipt_id=goods_receipt_id,
        code=code,
    )
    return [SupplierBillResponse.model_validate(bill) for bill in bills]


@bills_router.get(
    "/{bill_id}",
    response_model=SupplierBillResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener una factura de proveedor",
    dependencies=[Depends(require_purchasing)],
)
def get_supplier_bill(
    bill_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> SupplierBillResponse:
    """Devuelve el detalle de una cuenta por pagar o 404 si no existe."""
    bill = services.get_supplier_bill(db, bill_id)
    return SupplierBillResponse.model_validate(bill)


@bills_router.patch(
    "/{bill_id}",
    response_model=None,
    status_code=status.HTTP_200_OK,
    summary="Bloquear la edición de una factura",
    dependencies=[Depends(require_purchasing)],
)
def update_supplier_bill(
    bill_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> None:
    """Rechaza la edición: una factura registrada es inmutable (400)."""
    services.reject_bill_mutation(db, bill_id)


@bills_router.delete(
    "/{bill_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Bloquear el borrado de una factura",
    dependencies=[Depends(require_purchasing)],
)
def delete_supplier_bill(
    bill_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> None:
    """Rechaza el borrado: conserve la trazabilidad financiera (400)."""
    services.reject_bill_mutation(db, bill_id)


@bills_router.post(
    "/{bill_id}/pay",
    response_model=SupplierBillResponse,
    status_code=status.HTTP_200_OK,
    summary="Registrar un abono a una factura",
)
def pay_supplier_bill(
    payload: SupplierBillPaymentCreate,
    bill_id: int = Path(gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_purchasing),
) -> SupplierBillResponse:
    """Aplica un abono parcial o total; usa el usuario como referencia."""
    if payload.reference is None:
        payload = payload.model_copy(update={"reference": current_user.username})
    bill = services.register_bill_payment(db, bill_id, payload)
    return SupplierBillResponse.model_validate(bill)


@bills_router.get(
    "/{bill_id}/payments",
    response_model=list[SupplierBillPaymentResponse],
    status_code=status.HTTP_200_OK,
    summary="Historial de abonos de una factura",
    dependencies=[Depends(require_purchasing)],
)
def list_bill_payments(
    bill_id: int = Path(gt=0),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[SupplierBillPaymentResponse]:
    """Devuelve los abonos registrados, del más antiguo al más reciente."""
    payments = services.list_bill_payments(db, bill_id=bill_id, skip=skip, limit=limit)
    return [SupplierBillPaymentResponse.model_validate(item) for item in payments]


@bills_router.post(
    "/{bill_id}/void",
    response_model=SupplierBillResponse,
    status_code=status.HTTP_200_OK,
    summary="Anular una factura sin pagos",
    dependencies=[Depends(require_purchasing)],
)
def void_supplier_bill(
    bill_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> SupplierBillResponse:
    """Anula la factura sin borrarla ni alterar su historial."""
    bill = services.void_supplier_bill(db, bill_id)
    return SupplierBillResponse.model_validate(bill)


# --------------------------------------------------------------------------- #
# Agregación
# --------------------------------------------------------------------------- #

router = APIRouter()
router.include_router(suppliers_router)
router.include_router(orders_router)
router.include_router(receipts_router)
router.include_router(bills_router)
