/**
 * Capa de integración del módulo de Compras y Proveedores.
 *
 * Contratos TypeScript derivados de `backend/src/modules/purchasing/schemas.py`
 * y de `specs/purchasing_spec.md`. Todas las peticiones apuntan a
 * `/api/v1/purchasing`. El catálogo de productos y las bodegas se consultan a
 * través de `api/inventory.ts` (el rol `PURCHASING` solo tiene `inventory:read`).
 *
 * Pydantic serializa `Decimal` como string, de modo que los importes se reciben
 * como `string` para no perder precisión monetaria. Al enviar, las vistas
 * construyen cadenas con dos decimales.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "./client";
import { buildQuery } from "./config";
import { inventoryKeys } from "./inventory";

export { ApiError as PurchasingApiError } from "./client";

const PURCHASING_PATH = "/api/v1/purchasing";

// --------------------------------------------------------------------------- //
// Tipos de dominio
// --------------------------------------------------------------------------- //

/** Estados devueltos por `PurchaseOrderStatus` en el backend. */
export const PURCHASE_ORDER_STATUSES = [
  "DRAFT",
  "SENT",
  "APPROVED",
  "PARTIALLY_RECEIVED",
  "COMPLETED",
  "FORCE_CLOSED",
  "CANCELLED",
] as const;

export type PurchaseOrderStatus = (typeof PURCHASE_ORDER_STATUSES)[number];

export interface Supplier {
  id: number;
  tax_id: string;
  company_name: string;
  contact_name: string;
  email: string;
  phone: string | null;
  address: string;
  payment_terms_days: number;
  is_active: boolean;
  created_at: string;
}

export interface SupplierCreate {
  tax_id: string;
  company_name: string;
  contact_name: string;
  email: string;
  phone?: string | null;
  address: string;
  payment_terms_days?: number;
  is_active?: boolean;
}

/** Actualización parcial (PATCH); `phone` es el único campo que acepta `null`. */
export interface SupplierUpdate {
  tax_id?: string;
  company_name?: string;
  contact_name?: string;
  email?: string;
  phone?: string | null;
  address?: string;
  payment_terms_days?: number;
  is_active?: boolean;
}

export interface PurchaseOrderItem {
  id: number;
  purchase_order_id: number;
  product_id: number;
  quantity: number;
  received_quantity: number;
  unit_price: string;
  tax_rate: string;
  /** Calculado por el backend como `quantity × unit_price`. */
  subtotal: string;
}

export interface PurchaseOrderItemInput {
  product_id: number;
  quantity: number;
  unit_price: number | string;
  /** Porcentaje de impuesto, por ejemplo `"19.00"`. */
  tax_rate?: number | string;
}

export interface PurchaseOrder {
  id: number;
  code: string;
  supplier_id: number;
  status: PurchaseOrderStatus;
  issue_date: string;
  expected_delivery_date: string;
  subtotal: string;
  tax_amount: string;
  total: string;
  created_at: string;
  items: PurchaseOrderItem[];
}

export interface PurchaseOrderCreate {
  code?: string;
  supplier_id: number;
  issue_date?: string;
  expected_delivery_date: string;
  items: PurchaseOrderItemInput[];
}

/** Edición parcial: el `code` nunca se modifica y solo aplica en `DRAFT`. */
export interface PurchaseOrderUpdate {
  supplier_id?: number;
  issue_date?: string;
  expected_delivery_date?: string;
  items?: PurchaseOrderItemInput[];
}

export interface GoodsReceiptItemCreate {
  purchase_order_item_id: number;
  quantity: number;
}

export interface GoodsReceiptCreate {
  code?: string;
  purchase_order_id: number;
  warehouse_id: number;
  receipt_date?: string;
  received_by?: string | null;
  notes?: string | null;
  items: GoodsReceiptItemCreate[];
}

export interface GoodsReceiptItem {
  id: number;
  goods_receipt_id: number;
  purchase_order_item_id: number;
  quantity: number;
}

export interface GoodsReceipt {
  id: number;
  code: string;
  purchase_order_id: number;
  warehouse_id: number;
  receipt_date: string;
  received_by: string | null;
  notes: string | null;
  created_at: string;
  items: GoodsReceiptItem[];
}

// --------------------------------------------------------------------------- //
// Filtros y paginación
// --------------------------------------------------------------------------- //

export interface PaginationFilters {
  skip?: number;
  limit?: number;
}

export interface SupplierFilters extends PaginationFilters {
  company_name?: string;
  tax_id?: string;
  is_active?: boolean;
}

export interface PurchaseOrderFilters extends PaginationFilters {
  status?: PurchaseOrderStatus;
  supplier_id?: number;
  code?: string;
}

export interface GoodsReceiptFilters extends PaginationFilters {
  purchase_order_id?: number;
  warehouse_id?: number;
}

// --------------------------------------------------------------------------- //
// Clientes HTTP
// --------------------------------------------------------------------------- //

export function listSuppliers(
  filters: SupplierFilters = {},
): Promise<Supplier[]> {
  return apiRequest<Supplier[]>(
    `${PURCHASING_PATH}/suppliers${buildQuery(filters)}`,
  );
}

export function createSupplier(payload: SupplierCreate): Promise<Supplier> {
  return apiRequest<Supplier>(`${PURCHASING_PATH}/suppliers`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateSupplier(
  supplierId: number,
  payload: SupplierUpdate,
): Promise<Supplier> {
  return apiRequest<Supplier>(`${PURCHASING_PATH}/suppliers/${supplierId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

// --------------------------------------------------------------------------- //
// Órdenes de compra — /api/v1/purchasing/orders
// --------------------------------------------------------------------------- //

export function listPurchaseOrders(
  filters: PurchaseOrderFilters = {},
): Promise<PurchaseOrder[]> {
  return apiRequest<PurchaseOrder[]>(
    `${PURCHASING_PATH}/orders${buildQuery(filters)}`,
  );
}

export function createPurchaseOrder(
  payload: PurchaseOrderCreate,
): Promise<PurchaseOrder> {
  return apiRequest<PurchaseOrder>(`${PURCHASING_PATH}/orders`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updatePurchaseOrder(
  orderId: number,
  payload: PurchaseOrderUpdate,
): Promise<PurchaseOrder> {
  return apiRequest<PurchaseOrder>(`${PURCHASING_PATH}/orders/${orderId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

/** Aprueba la OC (`send: false`) o la marca como enviada (`send: true`). */
export function approvePurchaseOrder(
  orderId: number,
  send: boolean,
): Promise<PurchaseOrder> {
  return apiRequest<PurchaseOrder>(
    `${PURCHASING_PATH}/orders/${orderId}/approve`,
    {
      method: "POST",
      body: JSON.stringify({ send }),
    },
  );
}

export function cancelPurchaseOrder(
  orderId: number,
  reason: string | null,
): Promise<PurchaseOrder> {
  return apiRequest<PurchaseOrder>(`${PURCHASING_PATH}/orders/${orderId}/cancel`, {
    method: "POST",
    body: JSON.stringify(reason === null ? {} : { reason }),
  });
}

export function forceClosePurchaseOrder(orderId: number): Promise<PurchaseOrder> {
  return apiRequest<PurchaseOrder>(
    `${PURCHASING_PATH}/orders/${orderId}/force-close`,
    { method: "POST" },
  );
}

// --------------------------------------------------------------------------- //
// Recepción de mercancía — /api/v1/purchasing/receipts
// --------------------------------------------------------------------------- //

export function createGoodsReceipt(
  payload: GoodsReceiptCreate,
): Promise<GoodsReceipt> {
  return apiRequest<GoodsReceipt>(`${PURCHASING_PATH}/receipts`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listGoodsReceipts(
  filters: GoodsReceiptFilters = {},
): Promise<GoodsReceipt[]> {
  return apiRequest<GoodsReceipt[]>(
    `${PURCHASING_PATH}/receipts${buildQuery(filters)}`,
  );
}

// --------------------------------------------------------------------------- //
// Claves de caché de TanStack Query
// --------------------------------------------------------------------------- //

export const purchasingKeys = {
  all: ["purchasing"] as const,
  suppliers: {
    all: ["purchasing", "suppliers"] as const,
    list: (filters: SupplierFilters) =>
      ["purchasing", "suppliers", "list", filters] as const,
  },
  orders: {
    all: ["purchasing", "orders"] as const,
    list: (filters: PurchaseOrderFilters) =>
      ["purchasing", "orders", "list", filters] as const,
    detail: (orderId: number) =>
      ["purchasing", "orders", "detail", orderId] as const,
  },
  receipts: {
    all: ["purchasing", "receipts"] as const,
    list: (filters: GoodsReceiptFilters) =>
      ["purchasing", "receipts", "list", filters] as const,
  },
} as const;

// --------------------------------------------------------------------------- //
// Hooks de TanStack Query v5
// --------------------------------------------------------------------------- //

/** Lista proveedores con búsqueda por NIT/razón social y filtro de estado. */
export function useSuppliers(filters: SupplierFilters = {}) {
  return useQuery({
    queryKey: purchasingKeys.suppliers.list(filters),
    queryFn: () => listSuppliers(filters),
  });
}

export function useCreateSupplier() {
  const queryClient = useQueryClient();
  return useMutation<Supplier, Error, SupplierCreate>({
    mutationFn: createSupplier,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: purchasingKeys.suppliers.all,
      });
    },
  });
}

export interface UpdateSupplierVariables {
  supplierId: number;
  payload: SupplierUpdate;
}

export function useUpdateSupplier() {
  const queryClient = useQueryClient();
  return useMutation<Supplier, Error, UpdateSupplierVariables>({
    mutationFn: ({ supplierId, payload }) => updateSupplier(supplierId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: purchasingKeys.suppliers.all,
      });
      // El estado del proveedor afecta a las OC que se puedan crear.
      void queryClient.invalidateQueries({ queryKey: purchasingKeys.orders.all });
    },
  });
}

/** Lista OC con filtros por estado, proveedor o código. */
export function usePurchaseOrders(filters: PurchaseOrderFilters = {}) {
  return useQuery({
    queryKey: purchasingKeys.orders.list(filters),
    queryFn: () => listPurchaseOrders(filters),
  });
}

export function useCreatePurchaseOrder() {
  const queryClient = useQueryClient();
  return useMutation<PurchaseOrder, Error, PurchaseOrderCreate>({
    mutationFn: createPurchaseOrder,
    onSuccess: (order) => {
      queryClient.setQueryData(purchasingKeys.orders.detail(order.id), order);
      void queryClient.invalidateQueries({ queryKey: purchasingKeys.orders.all });
    },
  });
}

export interface UpdatePurchaseOrderVariables {
  orderId: number;
  payload: PurchaseOrderUpdate;
}

export function useUpdatePurchaseOrder() {
  const queryClient = useQueryClient();
  return useMutation<PurchaseOrder, Error, UpdatePurchaseOrderVariables>({
    mutationFn: ({ orderId, payload }) => updatePurchaseOrder(orderId, payload),
    onSuccess: (order) => {
      queryClient.setQueryData(purchasingKeys.orders.detail(order.id), order);
      void queryClient.invalidateQueries({ queryKey: purchasingKeys.orders.all });
    },
  });
}

export interface ApproveOrderVariables {
  orderId: number;
  send: boolean;
}

/** Aprueba o envía una OC; ambos estados permiten iniciar recepciones. */
export function useApprovePurchaseOrder() {
  const queryClient = useQueryClient();
  return useMutation<PurchaseOrder, Error, ApproveOrderVariables>({
    mutationFn: ({ orderId, send }) => approvePurchaseOrder(orderId, send),
    onSuccess: (order) => {
      queryClient.setQueryData(purchasingKeys.orders.detail(order.id), order);
      void queryClient.invalidateQueries({ queryKey: purchasingKeys.orders.all });
    },
  });
}

export interface CancelOrderVariables {
  orderId: number;
  reason: string | null;
}

export function useCancelPurchaseOrder() {
  const queryClient = useQueryClient();
  return useMutation<PurchaseOrder, Error, CancelOrderVariables>({
    mutationFn: ({ orderId, reason }) => cancelPurchaseOrder(orderId, reason),
    onSuccess: (order) => {
      queryClient.setQueryData(purchasingKeys.orders.detail(order.id), order);
      void queryClient.invalidateQueries({ queryKey: purchasingKeys.orders.all });
    },
  });
}

/** Cierra forzosamente una OC con saldo pendiente de recepción. */
export function useForceClosePurchaseOrder() {
  const queryClient = useQueryClient();
  return useMutation<PurchaseOrder, Error, number>({
    mutationFn: forceClosePurchaseOrder,
    onSuccess: (order) => {
      queryClient.setQueryData(purchasingKeys.orders.detail(order.id), order);
      void queryClient.invalidateQueries({ queryKey: purchasingKeys.orders.all });
    },
  });
}

/**
 * Registra una recepción: incrementa stock y puede cerrar la OC.
 *
 * Se invalidan `inventory` y `purchasing` porque la operación es atómica y
 * afecta a existencias, movimientos, líneas recibidas y estado de la orden.
 */
export function useCreateGoodsReceipt() {
  const queryClient = useQueryClient();
  return useMutation<GoodsReceipt, Error, GoodsReceiptCreate>({
    mutationFn: createGoodsReceipt,
    onSuccess: (receipt) => {
      void queryClient.invalidateQueries({ queryKey: purchasingKeys.receipts.all });
      void queryClient.invalidateQueries({ queryKey: purchasingKeys.orders.all });
      void queryClient.invalidateQueries({
        queryKey: inventoryKeys.stock.all,
      });
      void queryClient.invalidateQueries({
        queryKey: inventoryKeys.movements.all,
      });
      queryClient.removeQueries({
        queryKey: purchasingKeys.orders.detail(receipt.purchase_order_id),
      });
    },
  });
}

export function useGoodsReceipts(
  filters: GoodsReceiptFilters = {},
  enabled = true,
) {
  return useQuery({
    queryKey: purchasingKeys.receipts.list(filters),
    queryFn: () => listGoodsReceipts(filters),
    enabled,
  });
}
