"""Routers FastAPI del módulo de Ventas y Facturación.

Expone los contratos de ``specs/sales_spec.md`` (sección 4) bajo el prefijo
``/api/v1/sales``, que se aplica al registrar este router en ``src.main``.

Todos los endpoints exigen un token válido con rol ``SALES``; el rol
``ADMINISTRATOR`` pasa automáticamente por el *superuser bypass* de
``require_roles`` (``specs/users_spec.md``, sección 4.3).

``sales_exception_handler`` traduce las excepciones de dominio a HTTP usando
el ``status_code`` declarado por cada clase (400/404/409).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.security import require_roles
from src.modules.sales import services
from src.modules.sales.models import InvoiceStatus, SalesOrderStatus
from src.modules.sales.schemas import (
    CreditNoteCreate,
    CreditNoteResponse,
    CustomerCreate,
    CustomerResponse,
    CustomerUpdate,
    InvoiceCreate,
    InvoicePaymentCreate,
    InvoicePaymentResponse,
    InvoiceResponse,
    SalesOrderCancelRequest,
    SalesOrderConfirmRequest,
    SalesOrderCreate,
    SalesOrderResponse,
    SalesOrderUpdate,
)
from src.modules.sales.services import SalesServiceError
from src.modules.users.models import RoleEnum, User

__all__ = ["router", "sales_exception_handler"]


# --------------------------------------------------------------------------- #
# Guardia RBAC (spec de users, sección 4.3)
# --------------------------------------------------------------------------- #

#: ``ADMINISTRATOR`` pasa siempre gracias al bypass interno de ``require_roles``.
require_sales = require_roles([RoleEnum.SALES])


async def sales_exception_handler(
    _request: Request, exc: SalesServiceError
) -> JSONResponse:
    """Convierte un error de dominio de ventas en una respuesta HTTP."""
    return JSONResponse(
        status_code=exc.status_code, content={"detail": str(exc)}
    )


# --------------------------------------------------------------------------- #
# Clientes — /api/v1/sales/customers
# --------------------------------------------------------------------------- #

customers_router = APIRouter(prefix="/customers", tags=["sales: customers"])


@customers_router.post(
    "",
    response_model=CustomerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un cliente",
    dependencies=[Depends(require_sales)],
)
def create_customer(
    payload: CustomerCreate,
    db: Session = Depends(get_db),
) -> CustomerResponse:
    """Registra un cliente validando la unicidad de su ``tax_id``."""
    customer = services.create_customer(db, payload)
    return CustomerResponse.model_validate(customer)


@customers_router.get(
    "",
    response_model=list[CustomerResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar clientes",
    dependencies=[Depends(require_sales)],
)
def list_customers(
    skip: int = Query(0, ge=0, description="Registros a omitir."),
    limit: int = Query(100, ge=1, le=200, description="Máximo de registros."),
    company_name: str | None = Query(
        None, description="Filtro parcial por razón social."
    ),
    tax_id: str | None = Query(
        None, description="Filtro parcial por identificador fiscal."
    ),
    is_active: bool | None = Query(None, description="Filtro por estado."),
    db: Session = Depends(get_db),
) -> list[CustomerResponse]:
    """Lista clientes con paginación y filtros por razón social o ``tax_id``."""
    customers = services.list_customers(
        db,
        skip=skip,
        limit=limit,
        company_name=company_name,
        tax_id=tax_id,
        is_active=is_active,
    )
    return [CustomerResponse.model_validate(customer) for customer in customers]


@customers_router.get(
    "/{customer_id}",
    response_model=CustomerResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener un cliente",
    dependencies=[Depends(require_sales)],
)
def get_customer(
    customer_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> CustomerResponse:
    """Devuelve el detalle de un cliente o 404 si no existe."""
    customer = services.get_customer(db, customer_id)
    return CustomerResponse.model_validate(customer)


@customers_router.patch(
    "/{customer_id}",
    response_model=CustomerResponse,
    status_code=status.HTTP_200_OK,
    summary="Actualizar un cliente",
    dependencies=[Depends(require_sales)],
)
def update_customer(
    payload: CustomerUpdate,
    customer_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> CustomerResponse:
    """Actualiza parcialmente un cliente o devuelve 404 si no existe."""
    customer = services.update_customer(db, customer_id, payload)
    return CustomerResponse.model_validate(customer)


# --------------------------------------------------------------------------- #
# Pedidos y cotizaciones — /api/v1/sales/orders
# --------------------------------------------------------------------------- #

orders_router = APIRouter(prefix="/orders", tags=["sales: orders"])


@orders_router.post(
    "",
    response_model=SalesOrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una cotización o pedido en borrador",
    dependencies=[Depends(require_sales)],
)
def create_sales_order(
    payload: SalesOrderCreate,
    db: Session = Depends(get_db),
) -> SalesOrderResponse:
    """Crea el pedido con totales calculados por el servidor."""
    order = services.create_sales_order(db, payload)
    return SalesOrderResponse.model_validate(order)


@orders_router.get(
    "",
    response_model=list[SalesOrderResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar pedidos",
    dependencies=[Depends(require_sales)],
)
def list_sales_orders(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    status: SalesOrderStatus | None = Query(None),
    customer_id: int | None = Query(None, gt=0),
    code: str | None = Query(None, description="Filtro parcial por código."),
    db: Session = Depends(get_db),
) -> list[SalesOrderResponse]:
    """Lista pedidos con filtros por estado, cliente o código."""
    orders = services.list_sales_orders(
        db,
        skip=skip,
        limit=limit,
        status=status,
        customer_id=customer_id,
        code=code,
    )
    return [SalesOrderResponse.model_validate(order) for order in orders]


@orders_router.get(
    "/{order_id}",
    response_model=SalesOrderResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener un pedido",
    dependencies=[Depends(require_sales)],
)
def get_sales_order(
    order_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> SalesOrderResponse:
    """Devuelve un pedido con sus líneas o 404 si no existe."""
    order = services.get_sales_order(db, order_id)
    return SalesOrderResponse.model_validate(order)


@orders_router.patch(
    "/{order_id}",
    response_model=SalesOrderResponse,
    status_code=status.HTTP_200_OK,
    summary="Editar un pedido en borrador",
    dependencies=[Depends(require_sales)],
)
def update_sales_order(
    payload: SalesOrderUpdate,
    order_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> SalesOrderResponse:
    """Edita un pedido solo mientras esté en ``DRAFT`` o ``QUOTATION``."""
    order = services.update_sales_order(db, order_id, payload)
    return SalesOrderResponse.model_validate(order)


@orders_router.post(
    "/{order_id}/confirm",
    response_model=SalesOrderResponse,
    status_code=status.HTTP_200_OK,
    summary="Confirmar un pedido y descontar inventario",
)
def confirm_sales_order(
    payload: SalesOrderConfirmRequest | None = None,
    order_id: int = Path(gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_sales),
) -> SalesOrderResponse:
    """Valida crédito, despacha stock y confirma el pedido de forma atómica."""
    order = services.confirm_sales_order(
        db,
        order_id,
        warehouse_id=payload.warehouse_id if payload else None,
        created_by=current_user.username,
    )
    return SalesOrderResponse.model_validate(order)


@orders_router.post(
    "/{order_id}/cancel",
    response_model=SalesOrderResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancelar un pedido",
)
def cancel_sales_order(
    payload: SalesOrderCancelRequest | None = None,
    order_id: int = Path(gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_sales),
) -> SalesOrderResponse:
    """Cancela el pedido y revierte su despacho si estaba ``CONFIRMED``."""
    order = services.cancel_sales_order(
        db,
        order_id,
        reason=payload.reason if payload else None,
        created_by=current_user.username,
    )
    return SalesOrderResponse.model_validate(order)


# --------------------------------------------------------------------------- #
# Facturación — /api/v1/sales/invoices
# --------------------------------------------------------------------------- #

invoices_router = APIRouter(prefix="/invoices", tags=["sales: invoices"])


@invoices_router.post(
    "",
    response_model=InvoiceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Emitir una factura",
    dependencies=[Depends(require_sales)],
)
def issue_invoice(
    payload: InvoiceCreate,
    db: Session = Depends(get_db),
) -> InvoiceResponse:
    """Emite una factura desde un pedido confirmado o como venta directa."""
    invoice = services.issue_invoice(db, payload)
    return InvoiceResponse.model_validate(invoice)


@invoices_router.get(
    "",
    response_model=list[InvoiceResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar facturas",
    dependencies=[Depends(require_sales)],
)
def list_invoices(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    status_filter: InvoiceStatus | None = Query(
        None, alias="status", description="Filtro por estado fiscal."
    ),
    customer_id: int | None = Query(None, gt=0),
    sales_order_id: int | None = Query(None, gt=0),
    code: str | None = Query(None, description="Filtro parcial por código."),
    db: Session = Depends(get_db),
) -> list[InvoiceResponse]:
    """Lista facturas con filtros por estado, cliente, pedido o código."""
    invoices = services.list_invoices(
        db,
        skip=skip,
        limit=limit,
        status=status_filter,
        customer_id=customer_id,
        sales_order_id=sales_order_id,
        code=code,
    )
    return [InvoiceResponse.model_validate(invoice) for invoice in invoices]


@invoices_router.get(
    "/{invoice_id}",
    response_model=InvoiceResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener una factura",
    dependencies=[Depends(require_sales)],
)
def get_invoice(
    invoice_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> InvoiceResponse:
    """Devuelve el detalle de una factura o 404 si no existe."""
    invoice = services.get_invoice(db, invoice_id)
    return InvoiceResponse.model_validate(invoice)


@invoices_router.patch(
    "/{invoice_id}",
    response_model=None,
    status_code=status.HTTP_200_OK,
    summary="Bloquear la edición de una factura emitida",
    dependencies=[Depends(require_sales)],
)
def update_invoice(
    invoice_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> None:
    """Rechaza la edición: una factura emitida es inmutable (400)."""
    services.reject_invoice_mutation(db, invoice_id)


@invoices_router.delete(
    "/{invoice_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Bloquear el borrado de una factura emitida",
    dependencies=[Depends(require_sales)],
)
def delete_invoice(
    invoice_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> None:
    """Rechaza el borrado: una factura emitida es inmutable (400)."""
    services.reject_invoice_mutation(db, invoice_id)


@invoices_router.post(
    "/{invoice_id}/pay",
    response_model=InvoiceResponse,
    status_code=status.HTTP_200_OK,
    summary="Registrar un pago sobre una factura",
    dependencies=[Depends(require_sales)],
)
def pay_invoice(
    payload: InvoicePaymentCreate,
    invoice_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> InvoiceResponse:
    """Aplica un pago parcial o total y actualiza ``balance_due``/``PAID``."""
    invoice = services.register_invoice_payment(db, invoice_id, payload)
    return InvoiceResponse.model_validate(invoice)


@invoices_router.get(
    "/{invoice_id}/payments",
    response_model=list[InvoicePaymentResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar el historial de pagos de una factura",
    dependencies=[Depends(require_sales)],
)
def list_invoice_payments(
    invoice_id: int = Path(gt=0),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[InvoicePaymentResponse]:
    """Devuelve los abonos registrados, del más antiguo al más reciente."""
    services.get_invoice(db, invoice_id)
    payments = services.list_invoice_payments(
        db, invoice_id=invoice_id, skip=skip, limit=limit
    )
    return [InvoicePaymentResponse.model_validate(payment) for payment in payments]


@invoices_router.post(
    "/{invoice_id}/void",
    response_model=InvoiceResponse,
    status_code=status.HTTP_200_OK,
    summary="Anular una factura emitida",
    dependencies=[Depends(require_sales)],
)
def void_invoice(
    invoice_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> InvoiceResponse:
    """Anula la factura sin borrarla ni alterar su historial."""
    invoice = services.void_invoice(db, invoice_id)
    return InvoiceResponse.model_validate(invoice)


@invoices_router.get(
    "/{invoice_id}/credit-notes",
    response_model=list[CreditNoteResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar notas crédito de una factura",
    dependencies=[Depends(require_sales)],
)
def list_credit_notes(
    invoice_id: int = Path(gt=0),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[CreditNoteResponse]:
    """Lista las notas crédito emitidas sobre la factura indicada."""
    services.get_invoice(db, invoice_id)
    notes = services.list_credit_notes(
        db, invoice_id=invoice_id, skip=skip, limit=limit
    )
    return [CreditNoteResponse.model_validate(note) for note in notes]


@invoices_router.post(
    "/{invoice_id}/credit-notes",
    response_model=CreditNoteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Emitir una nota crédito",
    dependencies=[Depends(require_sales)],
)
def issue_credit_note(
    payload: CreditNoteCreate,
    invoice_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> CreditNoteResponse:
    """Emite una contrapartida sin modificar ni borrar la factura original."""
    note = services.issue_credit_note(db, invoice_id, payload)
    return CreditNoteResponse.model_validate(note)


# --------------------------------------------------------------------------- #
# Router agregado
# --------------------------------------------------------------------------- #

router = APIRouter()
router.include_router(customers_router)
router.include_router(orders_router)
router.include_router(invoices_router)
