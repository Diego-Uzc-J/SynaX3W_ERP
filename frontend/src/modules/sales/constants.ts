/** Etiquetas y tonos de los estados comerciales del módulo de ventas. */

import type { InvoiceStatus, SalesOrderStatus } from "../../api/sales";

export const ORDER_STATUS_LABELS: Record<SalesOrderStatus, string> = {
  DRAFT: "Borrador",
  QUOTATION: "Cotización",
  CONFIRMED: "Confirmado",
  FULFILLED: "Entregado",
  CANCELLED: "Cancelado",
};

export const ORDER_STATUS_HINTS: Record<SalesOrderStatus, string> = {
  DRAFT: "Editable; aún no reserva stock ni consume crédito.",
  QUOTATION: "Cotización enviada al cliente, pendiente de aprobación.",
  CONFIRMED: "Stock despachado y crédito validado; listo para facturar.",
  FULFILLED: "Entrega completada; solo admite facturación.",
  CANCELLED: "Documento cerrado; no admite más acciones.",
};

export const INVOICE_STATUS_LABELS: Record<InvoiceStatus, string> = {
  ISSUED: "Emitida",
  PAID: "Pagada",
  VOID: "Anulada",
};

export const INVOICE_STATUS_HINTS: Record<InvoiceStatus, string> = {
  ISSUED: "Emitida; admite abonos y notas crédito mientras tenga saldo.",
  PAID: "Pagada; solo admite notas crédito.",
  VOID: "Anulada; no admite pagos ni notas crédito.",
};

export type BadgeTone = "neutral" | "warning" | "success" | "strong" | "muted";

export const ORDER_STATUS_TONES: Record<SalesOrderStatus, BadgeTone> = {
  DRAFT: "neutral",
  QUOTATION: "warning",
  CONFIRMED: "success",
  FULFILLED: "strong",
  CANCELLED: "muted",
};

export const INVOICE_STATUS_TONES: Record<InvoiceStatus, BadgeTone> = {
  ISSUED: "warning",
  PAID: "success",
  VOID: "muted",
};

/** IVA por defecto de las líneas nuevas (Colombia). */
export const DEFAULT_TAX_RATE = "19.00";

/** Estados que permiten editar líneas antes de confirmar. */
export function isEditableOrderStatus(status: SalesOrderStatus): boolean {
  return status === "DRAFT" || status === "QUOTATION";
}

/** Estados desde los que se puede emitir factura. */
export function isInvoiceableOrderStatus(status: SalesOrderStatus): boolean {
  return status === "CONFIRMED" || status === "FULFILLED";
}

/** Estados que aún admiten cancelación (FULFILLED exige nota crédito). */
export function isCancellableOrderStatus(status: SalesOrderStatus): boolean {
  return (
    status === "DRAFT" || status === "QUOTATION" || status === "CONFIRMED"
  );
}
