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

/** Estados devueltos por `SupplierBillStatus` en el backend. */
export const SUPPLIER_BILL_STATUSES = [
  "PENDING",
  "PARTIALLY_PAID",
  "PAID",
  "VOID",
] as const;

export type SupplierBillStatus = (typeof SUPPLIER_BILL_STATUSES)[number];

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

/**
 * Cuenta por pagar de un proveedor.
 *
 * `total` y `balance_due` llegan como string porque el backend serializa
 * `Decimal` así. Ambos se derivan de `subtotal` + `tax_amount`.
 */
export interface SupplierBill {
  id: number;
  code: string;
  supplier_id: number;
  purchase_order_id: number | null;
  goods_receipt_id: number | null;
  supplier_invoice_number: string;
  status: SupplierBillStatus;
  issue_date: string;
  due_date: string;
  subtotal: string;
  tax_amount: string;
  total: string;
  balance_due: string;
  created_at: string;
}

export interface SupplierBillCreate {
  supplier_id: number;
  /** Al menos uno de `purchase_order_id` / `goods_receipt_id` debe indicarse. */
  purchase_order_id: number | null;
  goods_receipt_id: number | null;
  supplier_invoice_number: string;
  issue_date?: string;
  /** Si se omite, el backend la deriva de los plazos del proveedor. */
  due_date?: string | null;
  subtotal: number | string;
  tax_amount?: number | string;
  total?: number | string;
}

export interface SupplierBillPayment {
  id: number;
  bill_id: number;
  amount: string;
  paid_at: string;
  reference: string | null;
  created_at: string;
}

export interface SupplierBillPaymentCreate {
  amount: number | string;
  paid_at?: string;
  reference?: string | null;
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

export interface SupplierBillFilters extends PaginationFilters {
  status?: SupplierBillStatus;
  supplier_id?: number;
  purchase_order_id?: number;
  goods_receipt_id?: number;
  code?: string;
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

/** Detalle de una OC con sus líneas y cantidades pendientes de recepción. */
export function getPurchaseOrder(orderId: number): Promise<PurchaseOrder> {
  return apiRequest<PurchaseOrder>(`${PURCHASING_PATH}/orders/${orderId}`);
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
// Cuentas por pagar — /api/v1/purchasing/bills
// --------------------------------------------------------------------------- //

export function listSupplierBills(
  filters: SupplierBillFilters = {},
): Promise<SupplierBill[]> {
  return apiRequest<SupplierBill[]>(
    `${PURCHASING_PATH}/bills${buildQuery(filters)}`,
  );
}

export function getSupplierBill(billId: number): Promise<SupplierBill> {
  return apiRequest<SupplierBill>(`${PURCHASING_PATH}/bills/${billId}`);
}

export function createSupplierBill(
  payload: SupplierBillCreate,
): Promise<SupplierBill> {
  return apiRequest<SupplierBill>(`${PURCHASING_PATH}/bills`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function paySupplierBill(
  billId: number,
  payload: SupplierBillPaymentCreate,
): Promise<SupplierBill> {
  return apiRequest<SupplierBill>(`${PURCHASING_PATH}/bills/${billId}/pay`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listBillPayments(
  billId: number,
): Promise<SupplierBillPayment[]> {
  return apiRequest<SupplierBillPayment[]>(
    `${PURCHASING_PATH}/bills/${billId}/payments`,
  );
}

export function voidSupplierBill(billId: number): Promise<SupplierBill> {
  return apiRequest<SupplierBill>(`${PURCHASING_PATH}/bills/${billId}/void`, {
    method: "POST",
  });
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
  bills: {
    all: ["purchasing", "bills"] as const,
    list: (filters: SupplierBillFilters) =>
      ["purchasing", "bills", "list", filters] as const,
    detail: (billId: number) =>
      ["purchasing", "bills", "detail", billId] as const,
  },
  billPayments: {
    all: ["purchasing", "bill-payments"] as const,
    list: (billId: number) =>
      ["purchasing", "bill-payments", "list", billId] as const,
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

/** Detalle de una OC, usado por el formulario de recepciones y de facturas. */
export function usePurchaseOrder(orderId: number, enabled = true) {
  return useQuery({
    queryKey: purchasingKeys.orders.detail(orderId),
    queryFn: () => getPurchaseOrder(orderId),
    enabled: enabled && orderId > 0,
  });
}

// --------------------------------------------------------------------------- //
// Hooks de cuentas por pagar
// --------------------------------------------------------------------------- //

/** Lista facturas de proveedor con filtros de estado y documento origen. */
export function useSupplierBills(filters: SupplierBillFilters = {}) {
  return useQuery({
    queryKey: purchasingKeys.bills.list(filters),
    queryFn: () => listSupplierBills(filters),
  });
}

export function useSupplierBill(billId: number, enabled = true) {
  return useQuery({
    queryKey: purchasingKeys.bills.detail(billId),
    queryFn: () => getSupplierBill(billId),
    enabled: enabled && billId > 0,
  });
}

export function useBillPayments(billId: number, enabled = true) {
  return useQuery({
    queryKey: purchasingKeys.billPayments.list(billId),
    queryFn: () => listBillPayments(billId),
    enabled: enabled && billId > 0,
  });
}

export function useCreateSupplierBill() {
  const queryClient = useQueryClient();
  return useMutation<SupplierBill, Error, SupplierBillCreate>({
    mutationFn: createSupplierBill,
    onSuccess: (bill) => {
      queryClient.setQueryData(purchasingKeys.bills.detail(bill.id), bill);
      void queryClient.invalidateQueries({ queryKey: purchasingKeys.bills.all });
      void queryClient.invalidateQueries({ queryKey: purchasingKeys.orders.all });
    },
  });
}

/** Anula una factura sin pagos; conserva el documento y su historial. */
export function useVoidSupplierBill() {
  const queryClient = useQueryClient();
  return useMutation<SupplierBill, Error, number>({
    mutationFn: voidSupplierBill,
    onSuccess: (bill) => {
      queryClient.setQueryData(purchasingKeys.bills.detail(bill.id), bill);
      void queryClient.invalidateQueries({ queryKey: purchasingKeys.bills.all });
    },
  });
}

/** Aplica un abono y actualiza saldo/estado de la factura. */
export function usePaySupplierBill() {
  const queryClient = useQueryClient();
  return useMutation<
    SupplierBill,
    Error,
    { billId: number; payload: SupplierBillPaymentCreate }
  >({
    mutationFn: ({ billId, payload }) => paySupplierBill(billId, payload),
    onSuccess: (bill) => {
      queryClient.setQueryData(purchasingKeys.bills.detail(bill.id), bill);
      void queryClient.invalidateQueries({ queryKey: purchasingKeys.bills.all });
      void queryClient.invalidateQueries({
        queryKey: purchasingKeys.billPayments.all,
      });
    },
  });
}
