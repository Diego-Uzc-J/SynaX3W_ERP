import type { InvoiceStatus, SalesOrderStatus } from "../../api/sales";
import {
  INVOICE_STATUS_LABELS,
  INVOICE_STATUS_TONES,
  ORDER_STATUS_LABELS,
  ORDER_STATUS_TONES,
} from "./constants";
import type { BadgeTone } from "./constants";

const TONE_CLASSES: Record<BadgeTone, string> = {
  neutral: "bg-concrete-100 text-ink-500",
  warning: "bg-clay-100 text-clay-600",
  success: "bg-pine-100 text-pine-600",
  strong: "bg-ink-950 text-concrete-50",
  muted: "bg-concrete-100 text-concrete-400",
};

const DOT_CLASSES: Record<BadgeTone, string> = {
  neutral: "bg-concrete-400",
  warning: "bg-clay-600",
  success: "bg-pine-600",
  strong: "bg-signal-500",
  muted: "bg-concrete-400",
};

function Badge({ tone, label }: { tone: BadgeTone; label: string }) {
  return (
    <span
      className={[
        "inline-flex items-center gap-1.5 px-2 py-1 text-xs font-semibold",
        TONE_CLASSES[tone],
      ].join(" ")}
    >
      <span className={["size-1.5", DOT_CLASSES[tone]].join(" ")} aria-hidden="true" />
      {label}
    </span>
  );
}

/** Estado del pedido con el tono que le corresponde en la tabla. */
export function OrderStatusBadge({ status }: { status: SalesOrderStatus }) {
  return <Badge tone={ORDER_STATUS_TONES[status]} label={ORDER_STATUS_LABELS[status]} />;
}

/** Estado fiscal de la factura. */
export function InvoiceStatusBadge({ status }: { status: InvoiceStatus }) {
  return <Badge tone={INVOICE_STATUS_TONES[status]} label={INVOICE_STATUS_LABELS[status]} />;
}

/** Indicador de alta/baja del cliente. */
export function ActiveBadge({ isActive }: { isActive: boolean }) {
  return (
    <Badge
      tone={isActive ? "success" : "muted"}
      label={isActive ? "Activo" : "Inactivo"}
    />
  );
}
