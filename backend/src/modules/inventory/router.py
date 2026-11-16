"""Routers FastAPI del módulo de Inventario y Logística.

Expone los contratos de ``specs/inventory_spec.md`` (sección 4). El prefijo
``/api/v1/inventory`` se aplica al registrar este router en ``src.main``.

El manejador ``inventory_exception_handler`` traduce las excepciones de dominio
de ``services.py`` a respuestas HTTP:

- ``ResourceNotFoundError`` -> 404 Not Found
- ``DuplicateResourceError`` -> 409 Conflict
- ``InvalidMovementError`` -> 400 Bad Request
- ``InsufficientStockError`` -> 400 Bad Request (escenario 2 de la spec)
- ``ImmutableMovementError`` -> 409 Conflict
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from src.core.database import get_db
from src.core.security import require_roles
from src.modules.inventory import services
from src.modules.inventory.models import MovementType
from src.modules.inventory.schemas import (
    ProductCreate,
    ProductResponse,
    ProductUpdate,
    StockMovementCreate,
    StockMovementResponse,
    StockResponse,
    WarehouseCreate,
    WarehouseResponse,
    WarehouseUpdate,
)
from src.modules.inventory.services import (
    DuplicateResourceError,
    ImmutableMovementError,
    InsufficientStockError,
    InvalidMovementError,
    InventoryError,
    ResourceNotFoundError,
)
from src.modules.users.models import RoleEnum

__all__ = ["inventory_exception_handler", "router"]


# --------------------------------------------------------------------------- #
# Guardias RBAC (spec de users, sección 4.3)
# --------------------------------------------------------------------------- #

#: Roles con escritura completa en inventario (``ADMINISTRATOR`` pasa siempre).
INVENTORY_WRITE_ROLES = [RoleEnum.INVENTORY]

#: Roles con acceso de solo lectura: ``SALES`` (stock), ``PURCHASING``
#: (productos/proveedores) y ``MANUFACTURING`` (materias primas). ``ACCOUNTING``
#: y ``HR`` no incluyen ``inventory`` en su matriz de módulos.
INVENTORY_READ_ROLES = [
    RoleEnum.INVENTORY,
    RoleEnum.SALES,
    RoleEnum.PURCHASING,
    RoleEnum.MANUFACTURING,
]

require_inventory_write = require_roles(INVENTORY_WRITE_ROLES)
require_inventory_read = require_roles(INVENTORY_READ_ROLES)


_ERROR_STATUS: tuple[tuple[type[InventoryError], int], ...] = (
    (ResourceNotFoundError, status.HTTP_404_NOT_FOUND),
    (DuplicateResourceError, status.HTTP_409_CONFLICT),
    (InvalidMovementError, status.HTTP_400_BAD_REQUEST),
    (InsufficientStockError, status.HTTP_400_BAD_REQUEST),
    (ImmutableMovementError, status.HTTP_409_CONFLICT),
)


async def inventory_exception_handler(
    request: Request, exc: InventoryError
) -> JSONResponse:
    """Convierte un error de dominio de inventario en una respuesta HTTP."""
    status_code = next(
        (
            code
            for error_class, code in _ERROR_STATUS
            if isinstance(exc, error_class)
        ),
        status.HTTP_400_BAD_REQUEST,
    )
    return JSONResponse(status_code=status_code, content={"detail": str(exc)})


# --------------------------------------------------------------------------- #
# Productos — /api/v1/inventory/products
# --------------------------------------------------------------------------- #

products_router = APIRouter(prefix="/products", tags=["inventory: products"])


@products_router.post(
    "",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear un producto",
    dependencies=[Depends(require_inventory_write)],
)
def create_product(
    payload: ProductCreate,
    db: Session = Depends(get_db),
) -> ProductResponse:
    """Registra un producto en el catálogo validando la unicidad del SKU."""
    product = services.create_product(db, payload)
    return ProductResponse.model_validate(product)


@products_router.get(
    "",
    response_model=list[ProductResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar productos",
    dependencies=[Depends(require_inventory_read)],
)
def list_products(
    skip: int = Query(0, ge=0, description="Registros a omitir."),
    limit: int = Query(100, ge=1, le=200, description="Máximo de registros."),
    sku: str | None = Query(None, description="Filtro parcial por SKU."),
    name: str | None = Query(None, description="Filtro parcial por nombre."),
    is_active: bool | None = Query(None, description="Filtro por estado."),
    db: Session = Depends(get_db),
) -> list[ProductResponse]:
    """Lista productos con paginación y filtros por SKU o nombre."""
    products = services.list_products(
        db,
        skip=skip,
        limit=limit,
        sku=sku,
        name=name,
        is_active=is_active,
    )
    return [ProductResponse.model_validate(product) for product in products]


@products_router.get(
    "/{product_id}",
    response_model=ProductResponse,
    status_code=status.HTTP_200_OK,
    summary="Obtener un producto",
    dependencies=[Depends(require_inventory_read)],
)
def get_product(
    product_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> ProductResponse:
    """Devuelve el detalle de un producto o 404 si no existe."""
    product = services.get_product(db, product_id)
    return ProductResponse.model_validate(product)


@products_router.patch(
    "/{product_id}",
    response_model=ProductResponse,
    status_code=status.HTTP_200_OK,
    summary="Actualizar un producto",
    dependencies=[Depends(require_inventory_write)],
)
def update_product(
    payload: ProductUpdate,
    product_id: int = Path(gt=0),
    db: Session = Depends(get_db),
) -> ProductResponse:
    """Actualiza parcialmente un producto o devuelve 404 si no existe."""
    product = services.update_product(db, product_id, payload)
    return ProductResponse.model_validate(product)


# --------------------------------------------------------------------------- #
# Almacenes — /api/v1/inventory/warehouses
# --------------------------------------------------------------------------- #

warehouses_router = APIRouter(prefix="/warehouses", tags=["inventory: warehouses"])


@warehouses_router.post(
    "",
    response_model=WarehouseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un almacén",
    dependencies=[Depends(require_inventory_write)],
)
def create_warehouse(
    payload: WarehouseCreate,
    db: Session = Depends(get_db),
) -> WarehouseResponse:
    """Registra un almacén validando la unicidad de su código."""
    warehouse = services.create_warehouse(db, payload)
    return WarehouseResponse.model_validate(warehouse)


@warehouses_router.get(
    "",
    response_model=list[WarehouseResponse],
    status_code=status.HTTP_200_OK,
    summary="Listar almacenes",
    dependencies=[Depends(require_inventory_read)],
)
def list_warehouses(
    active_only: bool = Query(
        True, description="Si es True, solo devuelve almacenes activos."
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    code: str | None = Query(None, description="Filtro parcial por código."),
    name: str | None = Query(None, description="Filtro parcial por nombre."),
    db: Session = Depends(get_db),
) -> list[WarehouseResponse]:
    """Lista los almacenes activos (por defecto) con paginación."""
    warehouses = services.list_warehouses(
        db,
        active_only=active_only,
        skip=skip,
        limit=limit,
        code=code,
        name=name,
    )
    return [
        WarehouseResponse.model_validate(warehouse) for warehouse in warehouses
    ]


# --------------------------------------------------------------------------- #
# Movimientos de stock — /api/v1/inventory/movements
# --------------------------------------------------------------------------- #

movements_router = APIRouter(prefix="/movements", tags=["inventory: movements"])


@movements_router.post(
    "",
    response_model=StockMovementResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un movimiento de inventario",
    dependencies=[Depends(require_inventory_write)],
)
def create_stock_movement(
    payload: StockMovementCreate,
    db: Session = Depends(get_db),
) -> StockMovementResponse:
    """Registra el movimiento y actualiza ``Stock`` en una transacción atómica.

    Devuelve 400 si la operación dejaría stock negativo y
    ``ALLOW_NEGATIVE_STOCK`` está desactivado.
    """
    movement = services.create_stock_movement(db, payload)
    return StockMovementResponse.model_validate(movement)


@movements_router.get(
    "",
    response_model=list[StockMovementResponse],
    status_code=status.HTTP_200_OK,
    summary="Consultar el historial de movimientos",
    dependencies=[Depends(require_inventory_read)],
)
def list_stock_movements(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    product_id: int | None = Query(None, gt=0),
    warehouse_id: int | None = Query(
        None, gt=0, description="Coincide con bodega de origen o destino."
    ),
    movement_type: MovementType | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    db: Session = Depends(get_db),
) -> list[StockMovementResponse]:
    """Consulta el historial con filtros por fechas, producto o almacén."""
    movements = services.list_stock_movements(
        db,
        skip=skip,
        limit=limit,
        product_id=product_id,
        warehouse_id=warehouse_id,
        movement_type=movement_type,
        date_from=date_from,
        date_to=date_to,
    )
    return [
        StockMovementResponse.model_validate(movement) for movement in movements
    ]


# --------------------------------------------------------------------------- #
# Existencias — /api/v1/inventory/stock
# --------------------------------------------------------------------------- #

stock_router = APIRouter(prefix="/stock", tags=["inventory: stock"])


@stock_router.get(
    "",
    response_model=list[StockResponse],
    status_code=status.HTTP_200_OK,
    summary="Consultar niveles de existencias",
    dependencies=[Depends(require_inventory_read)],
)
def list_stock(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    product_id: int | None = Query(None, gt=0),
    warehouse_id: int | None = Query(None, gt=0),
    db: Session = Depends(get_db),
) -> list[StockResponse]:
    """Devuelve el saldo actual por producto y almacén."""
    stock_levels = services.list_stock(
        db,
        skip=skip,
        limit=limit,
        product_id=product_id,
        warehouse_id=warehouse_id,
    )
    return [StockResponse.model_validate(level) for level in stock_levels]


# --------------------------------------------------------------------------- #
# Router agregado
# --------------------------------------------------------------------------- #

router = APIRouter()
router.include_router(products_router)
router.include_router(warehouses_router)
router.include_router(movements_router)
router.include_router(stock_router)
