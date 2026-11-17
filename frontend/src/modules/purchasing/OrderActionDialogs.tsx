import { useState } from "react";

import {
  useApprovePurchaseOrder,
  useCancelPurchaseOrder,
  useForceClosePurchaseOrder,
} from "../../api/purchasing";
import type { PurchaseOrder } from "../../api/purchasing";
import { errorHint, errorMessage } from "./errors";
import { formatMoney } from "./format";
import GoodsReceiptForm from "./GoodsReceiptForm";
import PurchasingDialog from "./PurchasingDialog";

interface OrderDialogProps {
  open: boolean;
  order: PurchaseOrder | null;
  onClose: () => void;
  onDone: (message: string) => void;
}

interface ContentProps {
  order: PurchaseOrder;
  onClose: () => void;
  onDone: (message: string) => void;
}

const labelClass = "mb-1.5 block text-xs font-semibold text-ink-700";
const fieldClass =
  "w-full border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-950 " +
  "placeholder:text-concrete-400 focus:border-ink-950";
const secondaryButton =
  "border border-concrete-200 px-4 py-2 text-sm font-semibold text-ink-700 hover:border-ink-500 hover:text-ink-950";
const primaryButton =
  "bg-signal-500 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-signal-600 disabled:cursor-not-allowed disabled:opacity-60";

function ActionError({ error }: { error: unknown }) {
  const message = errorMessage(error);
  if (message === null) {
    return null;
  }
  const hint = errorHint(message);
  return (
    <div
      role="alert"
      className="border-l-2 border-signal-500 bg-signal-100 px-3 py-2 text-sm font-medium text-signal-600"
    >
      <p>{message}</p>
      {hint === null ? null : <p className="mt-1 font-normal">{hint}</p>}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Aprobar / enviar
// --------------------------------------------------------------------------- //

function ApproveOrderContent({ order, onClose, onDone }: ContentProps) {
  const approveMutation = useApprovePurchaseOrder();

  function handleApprove() {
    // El backend solo permite recepciones desde APPROVED/PARTIALLY_RECEIVED,
    // por lo que la vista aprueba directamente (nunca deja la OC en SENT).
    approveMutation.mutate(
      { orderId: order.id, send: false },
      {
        onSuccess: (approved) =>
          onDone(
            `Orden ${approved.code} aprobada; ya admite recepciones.`,
          ),
      },
    );
  }

  return (
    <PurchasingDialog
      open
      title={`Aprobar orden ${order.code}`}
      subtitle="La aprobación habilita el registro de recepciones de mercancía."
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose} className={secondaryButton}>
            Volver
          </button>
          <button
            type="button"
            onClick={handleApprove}
            disabled={approveMutation.isPending}
            className={primaryButton}
          >
            {approveMutation.isPending ? "Aprobando…" : "Aprobar orden"}
          </button>
        </>
      }
    >
      <dl className="grid grid-cols-2 gap-px border border-concrete-200 bg-concrete-200 text-sm">
        <div className="bg-white px-3 py-2.5">
          <dt className="text-xs font-semibold text-ink-500">Total de la OC</dt>
          <dd className="mt-0.5 font-semibold tabular-nums">
            {formatMoney(order.total)}
          </dd>
        </div>
        <div className="bg-white px-3 py-2.5">
          <dt className="text-xs font-semibold text-ink-500">Líneas</dt>
          <dd className="mt-0.5 font-semibold tabular-nums">
            {order.items.length}
          </dd>
        </div>
      </dl>

      <p className="border-l-2 border-clay-600 bg-clay-100 px-3 py-2 text-sm font-medium text-clay-600">
        La orden pasará a APPROVED. Solo se pueden recibir mercancías en estados
        APPROVED o PARTIALLY_RECEIVED.
      </p>

      <ActionError error={approveMutation.error} />
    </PurchasingDialog>
  );
}

export function ApproveOrderDialog({
  open,
  order,
  onClose,
  onDone,
}: OrderDialogProps) {
  if (!open || order === null) {
    return null;
  }
  return (
    <ApproveOrderContent order={order} onClose={onClose} onDone={onDone} />
  );
}

// --------------------------------------------------------------------------- //
// Recepción de mercancía
// --------------------------------------------------------------------------- //

/**
 * Acción rápida desde una OC: reutiliza el formulario completo de recepciones
 * con la orden ya preseleccionada.
 */
export function ReceiveOrderDialog({
  open,
  order,
  onClose,
  onDone,
}: OrderDialogProps) {
  return (
    <GoodsReceiptForm
      open={open && order !== null}
      order={order}
      onClose={onClose}
      onDone={onDone}
    />
  );
}

// --------------------------------------------------------------------------- //
// Cancelar
// --------------------------------------------------------------------------- //

function CancelOrderContent({ order, onClose, onDone }: ContentProps) {
  const [reason, setReason] = useState("");
  const cancelMutation = useCancelPurchaseOrder();

  function handleCancel() {
    const trimmed = reason.trim();
    cancelMutation.mutate(
      { orderId: order.id, reason: trimmed === "" ? null : trimmed },
      {
        onSuccess: (cancelled) =>
          onDone(`Orden ${cancelled.code} cancelada.`),
      },
    );
  }

  return (
    <PurchasingDialog
      open
      title={`Cancelar orden ${order.code}`}
      subtitle="La cancelación es definitiva y deja la orden en estado CANCELLED."
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose} className={secondaryButton}>
            Volver
          </button>
          <button
            type="button"
            onClick={handleCancel}
            disabled={cancelMutation.isPending}
            className={primaryButton}
          >
            {cancelMutation.isPending ? "Cancelando…" : "Cancelar orden"}
          </button>
        </>
      }
    >
      <p className="border-l-2 border-clay-600 bg-clay-100 px-3 py-2 text-sm font-medium text-clay-600">
        Solo se cancelan órdenes sin recepciones de inventario. Si ya recibiste
        mercancía, usa el cierre forzoso (FORCE_CLOSED).
      </p>

      <div>
        <label className={labelClass} htmlFor="cancel-reason">
          Motivo <span className="font-normal text-ink-500">(opcional, máx. 255)</span>
        </label>
        <textarea
          id="cancel-reason"
          rows={3}
          maxLength={255}
          value={reason}
          onChange={(event) => setReason(event.currentTarget.value)}
          placeholder="Ej. el proveedor canceló el suministro"
          className={fieldClass}
        />
      </div>

      <ActionError error={cancelMutation.error} />
    </PurchasingDialog>
  );
}

export function CancelOrderDialog({
  open,
  order,
  onClose,
  onDone,
}: OrderDialogProps) {
  if (!open || order === null) {
    return null;
  }
  return <CancelOrderContent order={order} onClose={onClose} onDone={onDone} />;
}

// --------------------------------------------------------------------------- //
// Cierre forzoso
// --------------------------------------------------------------------------- //

function ForceCloseContent({ order, onClose, onDone }: ContentProps) {
  const forceCloseMutation = useForceClosePurchaseOrder();

  function handleForceClose() {
    forceCloseMutation.mutate(order.id, {
      onSuccess: (closed) =>
        onDone(
          `Orden ${closed.code} cerrada forzosamente; el saldo pendiente quedó liberado.`,
        ),
    });
  }

  const pending = order.items.reduce(
    (total, item) => total + Math.max(0, item.quantity - item.received_quantity),
    0,
  );

  return (
    <PurchasingDialog
      open
      title={`Cerrar forzosamente ${order.code}`}
      subtitle="Libera el saldo pendiente sin registrar nuevas recepciones."
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose} className={secondaryButton}>
            Volver
          </button>
          <button
            type="button"
            onClick={handleForceClose}
            disabled={forceCloseMutation.isPending}
            className={primaryButton}
          >
            {forceCloseMutation.isPending ? "Cerrando…" : "Cerrar orden"}
          </button>
        </>
      }
    >
      <p className="border-l-2 border-clay-600 bg-clay-100 px-3 py-2 text-sm font-medium text-clay-600">
        Unidades pendientes de recibir: {pending}. Esta acción no modifica el
        inventario y deja la orden en FORCE_CLOSED.
      </p>
      <ActionError error={forceCloseMutation.error} />
    </PurchasingDialog>
  );
}

export function ForceCloseOrderDialog({
  open,
  order,
  onClose,
  onDone,
}: OrderDialogProps) {
  if (!open || order === null) {
    return null;
  }
  return <ForceCloseContent order={order} onClose={onClose} onDone={onDone} />;
}
