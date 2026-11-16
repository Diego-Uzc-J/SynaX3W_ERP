/**
 * Capa de integración del módulo de Inventario y Logística.
 *
 * Contratos TypeScript derivados de `backend/src/modules/inventory/schemas.py`
 * y de `specs/inventory_spec.md`. Todas las peticiones apuntan a los endpoints
 * expuestos bajo `/api/v1/inventory`.
 *
 * Nota: Pydantic serializa `Decimal` como string en JSON, por lo que
 * `unit_price` se recibe como `string` para no perder precisión monetaria.
 * Al enviar datos se acepta `string` o `number`.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

// --------------------------------------------------------------------------- //
// Configuración y entorno
// --------------------------------------------------------------------------- //

const configuredBaseUrl = import.meta.env?.VITE_API_URL?.trim();
const DEFAULT_API_BASE_URL = "http://localhost:8000";

/** URL base del backend, sin barra final. */
export const API_BASE_URL = (configuredBaseUrl || DEFAULT_API_BASE_URL).replace(
  /\/+$/,
  "",
);

const INVENTORY_PATH = "/api/v1/inventory";

// --------------------------------------------------------------------------- //
// Tipos de dominio
// --------------------------------------------------------------------------- //

export type MovementType = "INBOUND" | "OUTBOUND" | "TRANSFER" | "ADJUSTMENT";

export const MOVEMENT_TYPES: readonly MovementType[] = [
  "INBOUND",
  "OUTBOUND",
  "TRANSFER",
  "ADJUSTMENT",
] as const;

export interface Product {
  id: number;
  sku: string;
  name: string;
  description: string | null;
  /** Decimal serializado como string por Pydantic. */
  unit_price: string;
  minimum_stock: number;
  is_active: boolean;
  created_at: string;
}

export interface ProductCreate {
  sku: string;
  name: string;
  description?: string | null;
  unit_price: number | string;
  minimum_stock?: number;
  is_active?: boolean;
}

/** Actualización parcial (PATCH): todos los campos son opcionales. */
export interface ProductUpdate {
  sku?: string;
  name?: string;
  description?: string | null;
  unit_price?: number | string;
  minimum_stock?: number;
  is_active?: boolean;
}

export interface Warehouse {
  id: number;
  code: string;
  name: string;
  address: string | null;
  is_active: boolean;
  created_at: string;
}

export interface WarehouseCreate {
  code: string;
  name: string;
  address?: string | null;
  is_active?: boolean;
}

/** Actualización parcial (PATCH): todos los campos son opcionales. */
export interface WarehouseUpdate {
  code?: string;
  name?: string;
  address?: string | null;
  is_active?: boolean;
}

interface StockMovementBase {
  product_id: number;
  warehouse_source_id: number | null;
  warehouse_destination_id: number | null;
  movement_type: MovementType;
  /** Siempre mayor que cero. */
  quantity: number;
  reference_document: string;
  notes: string | null;
  created_by: string;
}

export interface StockMovement extends StockMovementBase {
  id: number;
  created_at: string;
}

/**
 * Payload de creación. Las bodegas y las notas son opcionales según el tipo:
 * INBOUND usa solo destino, OUTBOUND solo origen, TRANSFER ambos (distintos) y
 * ADJUSTMENT exactamente una.
 */
export interface StockMovementCreate
  extends Omit<
    StockMovementBase,
    "warehouse_source_id" | "warehouse_destination_id" | "notes"
  > {
  warehouse_source_id?: number | null;
  warehouse_destination_id?: number | null;
  notes?: string | null;
}

/** Saldo actual de un producto en un almacén concreto. */
export interface StockLevel {
  id: number;
  product_id: number;
  warehouse_id: number;
  quantity: number;
  updated_at: string;
}

// --------------------------------------------------------------------------- //
// Filtros y paginación
// --------------------------------------------------------------------------- //

export interface PaginationFilters {
  skip?: number;
  limit?: number;
}

export interface ProductFilters extends PaginationFilters {
  sku?: string;
  name?: string;
  is_active?: boolean;
}

export interface WarehouseFilters extends PaginationFilters {
  active_only?: boolean;
  code?: string;
  name?: string;
}

export interface MovementFilters extends PaginationFilters {
  product_id?: number;
  /** Coincide con la bodega de origen o de destino. */
  warehouse_id?: number;
  movement_type?: MovementType;
  date_from?: string;
  date_to?: string;
}

export interface StockFilters extends PaginationFilters {
  product_id?: number;
  warehouse_id?: number;
}

// --------------------------------------------------------------------------- //
// Cliente HTTP
// --------------------------------------------------------------------------- //

/** Error HTTP con el status y el payload devuelto por la API. */
export class InventoryApiError extends Error {
  readonly status: number;
  readonly payload: unknown;

  constructor(message: string, status: number, payload: unknown) {
    super(message);
    this.name = "InventoryApiError";
    this.status = status;
    this.payload = payload;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function extractErrorMessage(payload: unknown, status: number): string {
  if (isRecord(payload) && "detail" in payload) {
    const detail = payload.detail;
    if (typeof detail === "string" && detail.length > 0) {
      return detail;
    }
    // Errores de validación de FastAPI/Pydantic: `detail` es una lista.
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) =>
          isRecord(item) && typeof item.msg === "string"
            ? item.msg
            : String(item),
        )
        .filter((message) => message.length > 0);
      if (messages.length > 0) {
        return messages.join("; ");
      }
    }
  }
  return `Error HTTP ${status} al comunicarse con el módulo de inventario`;
}

function buildQuery(params: object): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(
    params as Record<string, unknown>,
  )) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    search.set(key, String(value));
  }
  const queryString = search.toString();
  return queryString ? `?${queryString}` : "";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  if (init?.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
  });

  if (!response.ok) {
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      payload = undefined;
    }
    throw new InventoryApiError(
      extractErrorMessage(payload, response.status),
      response.status,
      payload,
    );
  }

  return (await response.json()) as T;
}

// --------------------------------------------------------------------------- //
// Productos — /api/v1/inventory/products
// --------------------------------------------------------------------------- //

export function listProducts(
  filters: ProductFilters = {},
): Promise<Product[]> {
  return request<Product[]>(`${INVENTORY_PATH}/products${buildQuery(filters)}`);
}

export function getProduct(productId: number): Promise<Product> {
  return request<Product>(`${INVENTORY_PATH}/products/${productId}`);
}

export function createProduct(payload: ProductCreate): Promise<Product> {
  return request<Product>(`${INVENTORY_PATH}/products`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateProduct(
  productId: number,
  payload: ProductUpdate,
): Promise<Product> {
  return request<Product>(`${INVENTORY_PATH}/products/${productId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

// --------------------------------------------------------------------------- //
// Almacenes — /api/v1/inventory/warehouses
// --------------------------------------------------------------------------- //

export function listWarehouses(
  filters: WarehouseFilters = {},
): Promise<Warehouse[]> {
  return request<Warehouse[]>(
    `${INVENTORY_PATH}/warehouses${buildQuery(filters)}`,
  );
}

export function createWarehouse(payload: WarehouseCreate): Promise<Warehouse> {
  return request<Warehouse>(`${INVENTORY_PATH}/warehouses`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// --------------------------------------------------------------------------- //
// Movimientos — /api/v1/inventory/movements
// --------------------------------------------------------------------------- //

export function listMovements(
  filters: MovementFilters = {},
): Promise<StockMovement[]> {
  return request<StockMovement[]>(
    `${INVENTORY_PATH}/movements${buildQuery(filters)}`,
  );
}

export function createMovement(
  payload: StockMovementCreate,
): Promise<StockMovement> {
  return request<StockMovement>(`${INVENTORY_PATH}/movements`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// --------------------------------------------------------------------------- //
// Existencias — /api/v1/inventory/stock
// --------------------------------------------------------------------------- //

export function listStock(filters: StockFilters = {}): Promise<StockLevel[]> {
  return request<StockLevel[]>(
    `${INVENTORY_PATH}/stock${buildQuery(filters)}`,
  );
}

// --------------------------------------------------------------------------- //
// Claves de caché de TanStack Query
// --------------------------------------------------------------------------- //

export const inventoryKeys = {
  all: ["inventory"] as const,
  products: {
    all: ["inventory", "products"] as const,
    list: (filters: ProductFilters) =>
      ["inventory", "products", "list", filters] as const,
    detail: (productId: number) =>
      ["inventory", "products", "detail", productId] as const,
  },
  warehouses: {
    all: ["inventory", "warehouses"] as const,
    list: (filters: WarehouseFilters) =>
      ["inventory", "warehouses", "list", filters] as const,
  },
  movements: {
    all: ["inventory", "movements"] as const,
    list: (filters: MovementFilters) =>
      ["inventory", "movements", "list", filters] as const,
  },
  stock: {
    all: ["inventory", "stock"] as const,
    list: (filters: StockFilters) =>
      ["inventory", "stock", "list", filters] as const,
  },
} as const;

// --------------------------------------------------------------------------- //
// Hooks de TanStack Query v5
// --------------------------------------------------------------------------- //

/** Lista productos con paginación y filtros por SKU o nombre. */
export function useProducts(filters: ProductFilters = {}) {
  return useQuery({
    queryKey: inventoryKeys.products.list(filters),
    queryFn: () => listProducts(filters),
  });
}

/** Lista almacenes; por defecto la API devuelve solo los activos. */
export function useWarehouses(filters: WarehouseFilters = {}) {
  return useQuery({
    queryKey: inventoryKeys.warehouses.list(filters),
    queryFn: () => listWarehouses(filters),
  });
}

/** Saldos actuales por producto y almacén. */
export function useStock(filters: StockFilters = {}) {
  return useQuery({
    queryKey: inventoryKeys.stock.list(filters),
    queryFn: () => listStock(filters),
  });
}

/**
 * Crea un producto e invalida el catálogo.
 *
 * Las vistas de existencias derivan sus columnas y sus alertas de
 * `useProducts`, así que basta con refrescar `products.all`.
 */
export function useCreateProduct() {
  const queryClient = useQueryClient();

  return useMutation<Product, Error, ProductCreate>({
    mutationFn: createProduct,
    onSuccess: (product) => {
      queryClient.setQueryData(
        inventoryKeys.products.detail(product.id),
        product,
      );
      void queryClient.invalidateQueries({
        queryKey: inventoryKeys.products.all,
      });
    },
  });
}

export interface UpdateProductVariables {
  productId: number;
  payload: ProductUpdate;
}

/** Actualiza un producto (PATCH) y refresca el catálogo. */
export function useUpdateProduct() {
  const queryClient = useQueryClient();

  return useMutation<Product, Error, UpdateProductVariables>({
    mutationFn: ({ productId, payload }) => updateProduct(productId, payload),
    onSuccess: (product) => {
      queryClient.setQueryData(
        inventoryKeys.products.detail(product.id),
        product,
      );
      void queryClient.invalidateQueries({
        queryKey: inventoryKeys.products.all,
      });
    },
  });
}

/**
 * Registra una bodega e invalida el listado de almacenes.
 *
 * La tabla de existencias arma una columna por bodega a partir de este listado,
 * por lo que la invalidación también refresca esa vista.
 */
export function useCreateWarehouse() {
  const queryClient = useQueryClient();

  return useMutation<Warehouse, Error, WarehouseCreate>({
    mutationFn: createWarehouse,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: inventoryKeys.warehouses.all,
      });
    },
  });
}

/**
 * Registra un movimiento y refresca el historial.
 *
 * La API actualiza `Stock` en la misma transacción, por lo que las vistas que
 * dependan del historial se recargan al resolver la mutación.
 */
export function useCreateMovement() {
  const queryClient = useQueryClient();

  return useMutation<StockMovement, Error, StockMovementCreate>({
    mutationFn: createMovement,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: inventoryKeys.movements.all,
      });
      void queryClient.invalidateQueries({
        queryKey: inventoryKeys.stock.all,
      });
    },
  });
}
