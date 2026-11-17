/**
 * Capa de integración del módulo de Ventas y Facturación.
 *
 * Contratos TypeScript derivados de `backend/src/modules/sales/schemas.py` y de
 * `specs/sales_spec.md`. Todas las peticiones apuntan a `/api/v1/sales`.
 *
 * Pydantic serializa `Decimal` como string, de modo que los importes se
 * reciben como `string` para no perder precisión monetaria. Al enviar se acepta
 * `string` o `number`; las vistas construyen strings con dos decimales.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "./client";
import { buildQuery } from "./config";
import { inventoryKeys } from "./inventory";

export { ApiError as SalesApiError } from "./client";

const SALES_PATH = "/api/v1/sales";

// --------------------------------------------------------------------------- //
// Tipos de dominio
// --------------------------------------------------------------------------- //

export const SALES_ORDER_STATUSES = [
  "DRAFT",
  "QUOTATION",
  "CONFIRMED",
  "FULFILLED",
  "CANCELLED",
] as const;

export type SalesOrderStatus = (typeof SALES_ORDER_STATUSES)[number];

/** Estados que admiten edición de líneas y totales. */
export type EditableOrderStatus = Extract<
  SalesOrderStatus,
  "DRAFT" | "QUOTATION"
>;

export const INVOICE_STATUSES = ["ISSUED", "PAID", "VOID"] as const;

export type InvoiceStatus = (typeof INVOICE_STATUSES)[number];

export interface Customer {
  id: number;
  tax_id: string;
  company_name: string;
  contact_name: string;
  email: string;
  phone: string | null;
  address: string;
  /** Decimal serializado como string por Pydantic. */
  credit_limit: string;
  is_active: boolean;
  created_at: string;
}

export interface CustomerCreate {
  tax_id: string;
  company_name: string;
  contact_name: string;
  email: string;
  phone?: string | null;
  address: string;
  credit_limit?: number | string;
  is_active?: boolean;
}

/** Actualización parcial (PATCH); `phone` es el único campo que acepta `null`. */
export interface CustomerUpdate {
  tax_id?: string;
  company_name?: string;
  contact_name?: string;
  email?: string;
  phone?: string | null;
  address?: string;
  credit_limit?: number | string;
  is_active?: boolean;
}

export interface SalesOrderItem {
  id: number;
  sales_order_id: number;
  product_id: number;
  quantity: number;
  unit_price: string;
  tax_rate: string;
  subtotal: string;
}

export interface SalesOrderItemInput {
  product_id: number;
  quantity: number;
  unit_price: number | string;
  /** Porcentaje de IVA, por ejemplo `"19.00"`. */
  tax_rate: number | string;
}

export interface SalesOrder {
  id: number;
  code: string;
  customer_id: number;
  status: SalesOrderStatus;
  issue_date: string;
  valid_until: string | null;
  subtotal: string;
  tax_amount: string;
  total: string;
  created_at: string;
  items: SalesOrderItem[];
}

export interface SalesOrderCreate {
  code?: string;
  customer_id: number;
  status?: EditableOrderStatus;
  issue_date?: string;
  valid_until?: string | null;
  items: SalesOrderItemInput[];
}

/** Edición parcial: el `code` nunca se modifica. */
export interface SalesOrderUpdate {
  customer_id?: number;
  status?: EditableOrderStatus;
  issue_date?: string;
  valid_until?: string | null;
  items?: SalesOrderItemInput[];
}

export interface Invoice {
  id: number;
  code: string;
  sales_order_id: number | null;
  customer_id: number;
  status: InvoiceStatus;
  issue_date: string;
  due_date: string;
  total: string;
  balance_due: string;
  created_at: string;
}

export interface InvoiceCreate {
  code?: string;
  sales_order_id?: number | null;
  customer_id: number;
  issue_date?: string;
  due_date: string;
  total?: number | string | null;
}

export interface InvoicePayment {
  id: number;
  invoice_id: number;
  /** Decimal serializado como string por Pydantic. */
  amount: string;
  paid_at: string;
  created_at: string;
}

export interface InvoicePaymentCreate {
  amount: number | string;
}

export interface CreditNote {
  id: number;
  code: string;
  invoice_id: number;
  amount: string;
  reason: string | null;
  issue_date: string;
  created_at: string;
}

export interface CreditNoteCreate {
  code?: string;
  invoice_id?: number;
  amount: number | string;
  reason?: string | null;
  issue_date?: string;
}

// --------------------------------------------------------------------------- //
// Filtros y paginación
// --------------------------------------------------------------------------- //

export interface PaginationFilters {
  skip?: number;
  limit?: number;
}

export interface CustomerFilters extends PaginationFilters {
  company_name?: string;
  tax_id?: string;
  is_active?: boolean;
}

export interface SalesOrderFilters extends PaginationFilters {
  status?: SalesOrderStatus;
  customer_id?: number;
  code?: string;
}

export interface InvoiceFilters extends PaginationFilters {
  status?: InvoiceStatus;
  customer_id?: number;
  sales_order_id?: number;
  code?: string;
}

// --------------------------------------------------------------------------- //
// Clientes — /api/v1/sales/customers
// --------------------------------------------------------------------------- //

export function listCustomers(
  filters: CustomerFilters = {},
): Promise<Customer[]> {
  return apiRequest<Customer[]>(
    `${SALES_PATH}/customers${buildQuery(filters)}`,
  );
}

export function createCustomer(payload: CustomerCreate): Promise<Customer> {
  return apiRequest<Customer>(`${SALES_PATH}/customers`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateCustomer(
  customerId: number,
  payload: CustomerUpdate,
): Promise<Customer> {
  return apiRequest<Customer>(`${SALES_PATH}/customers/${customerId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

// --------------------------------------------------------------------------- //
// Pedidos y cotizaciones — /api/v1/sales/orders
// --------------------------------------------------------------------------- //

export function listSalesOrders(
  filters: SalesOrderFilters = {},
): Promise<SalesOrder[]> {
  return apiRequest<SalesOrder[]>(
    `${SALES_PATH}/orders${buildQuery(filters)}`,
  );
}

export function createSalesOrder(
  payload: SalesOrderCreate,
): Promise<SalesOrder> {
  return apiRequest<SalesOrder>(`${SALES_PATH}/orders`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateSalesOrder(
  orderId: number,
  payload: SalesOrderUpdate,
): Promise<SalesOrder> {
  return apiRequest<SalesOrder>(`${SALES_PATH}/orders/${orderId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

/**
 * Confirma el pedido y descuenta stock de la bodega indicada.
 *
 * `warehouseId` nulo envía `{}` para que el backend resuelva la única bodega
 * activa; con varias activas responde 400 y la vista muestra el mensaje.
 */
export function confirmSalesOrder(
  orderId: number,
  warehouseId: number | null,
): Promise<SalesOrder> {
  return apiRequest<SalesOrder>(`${SALES_PATH}/orders/${orderId}/confirm`, {
    method: "POST",
    body: JSON.stringify(
      warehouseId === null ? {} : { warehouse_id: warehouseId },
    ),
  });
}

export function cancelSalesOrder(
  orderId: number,
  reason: string | null,
): Promise<SalesOrder> {
  return apiRequest<SalesOrder>(`${SALES_PATH}/orders/${orderId}/cancel`, {
    method: "POST",
    body: JSON.stringify(reason === null ? {} : { reason }),
  });
}

// --------------------------------------------------------------------------- //
// Facturación — /api/v1/sales/invoices
// --------------------------------------------------------------------------- //

export function listInvoices(filters: InvoiceFilters = {}): Promise<Invoice[]> {
  return apiRequest<Invoice[]>(
    `${SALES_PATH}/invoices${buildQuery(filters)}`,
  );
}

export function issueInvoice(payload: InvoiceCreate): Promise<Invoice> {
  return apiRequest<Invoice>(`${SALES_PATH}/invoices`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getInvoice(invoiceId: number): Promise<Invoice> {
  return apiRequest<Invoice>(`${SALES_PATH}/invoices/${invoiceId}`);
}

export function registerInvoicePayment(
  invoiceId: number,
  payload: InvoicePaymentCreate,
): Promise<Invoice> {
  return apiRequest<Invoice>(`${SALES_PATH}/invoices/${invoiceId}/pay`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listInvoicePayments(
  invoiceId: number,
): Promise<InvoicePayment[]> {
  return apiRequest<InvoicePayment[]>(
    `${SALES_PATH}/invoices/${invoiceId}/payments`,
  );
}

export function listCreditNotes(invoiceId: number): Promise<CreditNote[]> {
  return apiRequest<CreditNote[]>(
    `${SALES_PATH}/invoices/${invoiceId}/credit-notes`,
  );
}

export function issueCreditNote(
  invoiceId: number,
  payload: CreditNoteCreate,
): Promise<CreditNote> {
  return apiRequest<CreditNote>(
    `${SALES_PATH}/invoices/${invoiceId}/credit-notes`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

// --------------------------------------------------------------------------- //
// Claves de caché de TanStack Query
// --------------------------------------------------------------------------- //

export const salesKeys = {
  all: ["sales"] as const,
  customers: {
    all: ["sales", "customers"] as const,
    list: (filters: CustomerFilters) =>
      ["sales", "customers", "list", filters] as const,
  },
  orders: {
    all: ["sales", "orders"] as const,
    list: (filters: SalesOrderFilters) =>
      ["sales", "orders", "list", filters] as const,
    detail: (orderId: number) =>
      ["sales", "orders", "detail", orderId] as const,
  },
  invoices: {
    all: ["sales", "invoices"] as const,
    list: (filters: InvoiceFilters) =>
      ["sales", "invoices", "list", filters] as const,
    detail: (invoiceId: number) =>
      ["sales", "invoices", "detail", invoiceId] as const,
    payments: (invoiceId: number) =>
      ["sales", "invoices", "payments", invoiceId] as const,
    creditNotes: (invoiceId: number) =>
      ["sales", "invoices", "credit-notes", invoiceId] as const,
  },
} as const;

// --------------------------------------------------------------------------- //
// Hooks de TanStack Query v5
// --------------------------------------------------------------------------- //

/** Lista clientes con búsqueda por razón social o identificador fiscal. */
export function useCustomers(filters: CustomerFilters = {}) {
  return useQuery({
    queryKey: salesKeys.customers.list(filters),
    queryFn: () => listCustomers(filters),
  });
}

export function useCreateCustomer() {
  const queryClient = useQueryClient();
  return useMutation<Customer, Error, CustomerCreate>({
    mutationFn: createCustomer,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: salesKeys.customers.all,
      });
    },
  });
}

export interface UpdateCustomerVariables {
  customerId: number;
  payload: CustomerUpdate;
}

export function useUpdateCustomer() {
  const queryClient = useQueryClient();
  return useMutation<Customer, Error, UpdateCustomerVariables>({
    mutationFn: ({ customerId, payload }) =>
      updateCustomer(customerId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: salesKeys.customers.all,
      });
    },
  });
}

/** Lista pedidos con filtros por estado, cliente o código. */
export function useSalesOrders(filters: SalesOrderFilters = {}) {
  return useQuery({
    queryKey: salesKeys.orders.list(filters),
    queryFn: () => listSalesOrders(filters),
  });
}

export function useCreateSalesOrder() {
  const queryClient = useQueryClient();
  return useMutation<SalesOrder, Error, SalesOrderCreate>({
    mutationFn: createSalesOrder,
    onSuccess: (order) => {
      queryClient.setQueryData(salesKeys.orders.detail(order.id), order);
      void queryClient.invalidateQueries({ queryKey: salesKeys.orders.all });
    },
  });
}

export interface UpdateOrderVariables {
  orderId: number;
  payload: SalesOrderUpdate;
}

export function useUpdateSalesOrder() {
  const queryClient = useQueryClient();
  return useMutation<SalesOrder, Error, UpdateOrderVariables>({
    mutationFn: ({ orderId, payload }) => updateSalesOrder(orderId, payload),
    onSuccess: (order) => {
      queryClient.setQueryData(salesKeys.orders.detail(order.id), order);
      void queryClient.invalidateQueries({ queryKey: salesKeys.orders.all });
    },
  });
}

export interface ConfirmOrderVariables {
  orderId: number;
  warehouseId: number | null;
}

/**
 * Confirma un pedido.
 *
 * Invalida las cachés de inventario porque la confirmación descuenta stock y
 * registra movimientos `OUTBOUND` en la misma transacción.
 */
export function useConfirmSalesOrder() {
  const queryClient = useQueryClient();
  return useMutation<SalesOrder, Error, ConfirmOrderVariables>({
    mutationFn: ({ orderId, warehouseId }) =>
      confirmSalesOrder(orderId, warehouseId),
    onSuccess: (order) => {
      queryClient.setQueryData(salesKeys.orders.detail(order.id), order);
      void queryClient.invalidateQueries({ queryKey: salesKeys.orders.all });
      void queryClient.invalidateQueries({
        queryKey: inventoryKeys.stock.all,
      });
      void queryClient.invalidateQueries({
        queryKey: inventoryKeys.movements.all,
      });
    },
  });
}

export interface CancelOrderVariables {
  orderId: number;
  reason: string | null;
}

/** Cancela un pedido; si estaba `CONFIRMED`, el backend revierte el stock. */
export function useCancelSalesOrder() {
  const queryClient = useQueryClient();
  return useMutation<SalesOrder, Error, CancelOrderVariables>({
    mutationFn: ({ orderId, reason }) => cancelSalesOrder(orderId, reason),
    onSuccess: (order) => {
      queryClient.setQueryData(salesKeys.orders.detail(order.id), order);
      void queryClient.invalidateQueries({ queryKey: salesKeys.orders.all });
      void queryClient.invalidateQueries({
        queryKey: inventoryKeys.stock.all,
      });
      void queryClient.invalidateQueries({
        queryKey: inventoryKeys.movements.all,
      });
    },
  });
}

/**
 * Lista facturas.
 *
 * `enabled` permite consultar solo cuando un diálogo está abierto (por
 * ejemplo, para calcular la deuda vigente de un cliente antes de confirmar).
 */
export function useInvoices(filters: InvoiceFilters = {}, enabled = true) {
  return useQuery({
    queryKey: salesKeys.invoices.list(filters),
    queryFn: () => listInvoices(filters),
    enabled,
  });
}

export function useIssueInvoice() {
  const queryClient = useQueryClient();
  return useMutation<Invoice, Error, InvoiceCreate>({
    mutationFn: issueInvoice,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: salesKeys.invoices.all });
    },
  });
}

/** Detalle de factura; `enabled` evita consultar identificadores inválidos. */
export function useInvoice(invoiceId: number, enabled = true) {
  return useQuery({
    queryKey: salesKeys.invoices.detail(invoiceId),
    queryFn: () => getInvoice(invoiceId),
    enabled: enabled && invoiceId > 0,
  });
}

export interface RegisterPaymentVariables {
  invoiceId: number;
  payload: InvoicePaymentCreate;
}

/** Registra un abono y refresca la factura, el listado y su historial. */
export function useRegisterInvoicePayment() {
  const queryClient = useQueryClient();
  return useMutation<Invoice, Error, RegisterPaymentVariables>({
    mutationFn: ({ invoiceId, payload }) =>
      registerInvoicePayment(invoiceId, payload),
    onSuccess: (invoice) => {
      queryClient.setQueryData(
        salesKeys.invoices.detail(invoice.id),
        invoice,
      );
      void queryClient.invalidateQueries({ queryKey: salesKeys.invoices.all });
      void queryClient.invalidateQueries({
        queryKey: salesKeys.invoices.payments(invoice.id),
      });
    },
  });
}

export function useInvoicePayments(invoiceId: number, enabled = true) {
  return useQuery({
    queryKey: salesKeys.invoices.payments(invoiceId),
    queryFn: () => listInvoicePayments(invoiceId),
    enabled: enabled && invoiceId > 0,
  });
}

export function useCreditNotes(invoiceId: number, enabled = true) {
  return useQuery({
    queryKey: salesKeys.invoices.creditNotes(invoiceId),
    queryFn: () => listCreditNotes(invoiceId),
    enabled: enabled && invoiceId > 0,
  });
}

export interface IssueCreditNoteVariables {
  invoiceId: number;
  payload: CreditNoteCreate;
}

/** Emite una nota crédito e invalida la factura y sus contrapartidas. */
export function useIssueCreditNote() {
  const queryClient = useQueryClient();
  return useMutation<CreditNote, Error, IssueCreditNoteVariables>({
    mutationFn: ({ invoiceId, payload }) =>
      issueCreditNote(invoiceId, payload),
    onSuccess: (note) => {
      void queryClient.invalidateQueries({ queryKey: salesKeys.invoices.all });
      void queryClient.invalidateQueries({
        queryKey: salesKeys.invoices.detail(note.invoice_id),
      });
      void queryClient.invalidateQueries({
        queryKey: salesKeys.invoices.creditNotes(note.invoice_id),
      });
    },
  });
}
