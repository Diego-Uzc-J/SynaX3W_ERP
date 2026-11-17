/** Etiquetas, tonos y reglas de transición de órdenes y cuentas por pagar. */

import type {
  PurchaseOrderStatus,
  SupplierBillStatus,
} from "../../api/purchasing";

export const ORDER_STATUS_LABELS: Record<PurchaseOrderStatus, string> = {
  DRAFT: "Borrador",
  SENT: "Enviada",
  APPROVED: "Aprobada",
  PARTIALLY_RECEIVED: "Recepción parcial",
  COMPLETED: "Completada",
  FORCE_CLOSED: "Cerrada forzosamente",
  CANCELLED: "Cancelada",
};

export const ORDER_STATUS_HINTS: Record<PurchaseOrderStatus, string> = {
  DRAFT: "Editable; aún no autoriza recepciones.",
  SENT: "Remitida al proveedor; ya puede recibirse mercancía.",
  APPROVED: "Aprobada; permite registrar recepciones de mercancía.",
  PARTIALLY_RECEIVED: "Con recepciones parciales; admite nuevas recepciones.",
  COMPLETED: "Todas las líneas fueron recibidas; documento cerrado.",
  FORCE_CLOSED: "Cerrada sin recibir el saldo pendiente; no admite más acciones.",
  CANCELLED: "Cancelada sin movimientos de inventario; documento cerrado.",
};

export type BadgeTone = "neutral" | "warning" | "success" | "strong" | "muted";

export const ORDER_STATUS_TONES: Record<PurchaseOrderStatus, BadgeTone> = {
  DRAFT: "neutral",
  SENT: "warning",
  APPROVED: "success",
  PARTIALLY_RECEIVED: "warning",
  COMPLETED: "strong",
  FORCE_CLOSED: "muted",
  CANCELLED: "muted",
};

/** IVA por defecto de las líneas nuevas (Colombia). */
export const DEFAULT_TAX_RATE = "19.00";

/** El backend solo permite editar líneas mientras la OC está en DRAFT. */
export function isEditableOrderStatus(status: PurchaseOrderStatus): boolean {
  return status === "DRAFT";
}

export function isApprovableOrderStatus(status: PurchaseOrderStatus): boolean {
  return status === "DRAFT";
}

/** El servicio admite recepciones desde APPROVED o PARTIALLY_RECEIVED. */
export function isReceivableOrderStatus(status: PurchaseOrderStatus): boolean {
  return status === "APPROVED" || status === "PARTIALLY_RECEIVED";
}

/** No se puede cancelar si hay recepciones: el backend exige FORCE_CLOSED. */
export function isCancellableOrderStatus(status: PurchaseOrderStatus): boolean {
  return status === "DRAFT" || status === "SENT" || status === "APPROVED";
}

export function isForceClosableOrderStatus(
  status: PurchaseOrderStatus,
): boolean {
  return isReceivableOrderStatus(status);
}

// --------------------------------------------------------------------------- //
// Cuentas por pagar
// --------------------------------------------------------------------------- //

export const BILL_STATUS_LABELS: Record<SupplierBillStatus, string> = {
  PENDING: "Pendiente",
  PARTIALLY_PAID: "Pago parcial",
  PAID: "Pagada",
  VOID: "Anulada",
};

export const BILL_STATUS_HINTS: Record<SupplierBillStatus, string> = {
  PENDING: "Registrada sin abonos; admite pagos y anulación.",
  PARTIALLY_PAID: "Con abonos parciales; admite nuevos pagos.",
  PAID: "Saldo cubierto; no admite más abonos.",
  VOID: "Anulada sin alterar su historial; no admite pagos.",
};

export const BILL_STATUS_TONES: Record<SupplierBillStatus, BadgeTone> = {
  PENDING: "warning",
  PARTIALLY_PAID: "warning",
  PAID: "success",
  VOID: "muted",
};

/** El servicio solo acepta abonos sobre facturas pendientes o pagas a medias. */
export function canPayBill(status: SupplierBillStatus): boolean {
  return status === "PENDING" || status === "PARTIALLY_PAID";
}

/** Solo se anulan facturas sin abonos; VOID es idempotente en el backend. */
export function canVoidBill(status: SupplierBillStatus): boolean {
  return status === "PENDING";
}
