import { useEffect, useMemo, useState } from "react";

import { useWarehouses } from "../../api/inventory";
import {
  useApprovePurchaseOrder,
  useCancelPurchaseOrder,
  useCreateGoodsReceipt,
  useForceClosePurchaseOrder,
} from "../../api/purchasing";
import type { PurchaseOrder } from "../../api/purchasing";
import { errorHint, errorMessage } from "./errors";
import { formatMoney, parseQuantity, todayIso } from "./format";
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

function ReceiveOrderContent({ order, onClose, onDone }: ContentProps) {
  const [warehouseId, setWarehouseId] = useState("");
  const [quantities, setQuantities] = useState<Record<number, string>>({});
  const [formError, setFormError] = useState<string | null>(null);

  const warehousesQuery = useWarehouses({ active_only: true, limit: 200 });
  const warehouses = warehousesQuery.data ?? [];
  const receiptMutation = useCreateGoodsReceipt();

  // Al abrir, se precarga el saldo pendiente de cada línea (máximo recibible).
  useEffect(() => {
    const initial: Record<number, string> = {};
    for (const item of order.items) {
      initial[item.id] = String(Math.max(0, item.quantity - item.received_quantity));
    }
    setQuantities(initial);
    setFormError(null);
  }, [order]);

  useEffect(() => {
    if (warehouseId !== "" || warehouses.length !== 1) {
      return;
    }
    const only = warehouses[0];
    if (only !== undefined) {
      setWarehouseId(String(only.id));
    }
  }, [warehouses, warehouseId]);

  const pendingByItem = useMemo(
    () =>
      new Map(
        order.items.map((item) => [
          item.id,
          Math.max(0, item.quantity - item.received_quantity),
        ]),
      ),
    [order.items],
  );

  function validate(): string | null {
    if (warehouseId === "") {
      return "Selecciona la bodega destino de la mercancía.";
    }
    let hasQuantity = false;
    for (const item of order.items) {
      const raw = quantities[item.id] ?? "0";
      const pending = pendingByItem.get(item.id) ?? 0;
      if (raw.trim() === "" || raw.trim() === "0") {
        continue;
      }
      const quantity = parseQuantity(raw);
      if (quantity === null) {
        return `Línea ${item.id}: usa una cantidad entera mayor que cero.`;
      }
      if (quantity > pending) {
        return `Línea ${item.id}: quedan ${pending} unidades pendientes; la recepción se rechazaría por sobre-recepción.`;
      }
      hasQuantity = true;
    }
    if (!hasQuantity) {
      return "Indica al menos una cantidad a recibir.";
    }
    return null;
  }

  function handleReceive() {
    const message = validate();
    if (message !== null) {
      setFormError(message);
      return;
    }
    setFormError(null);

    const items = order.items
      .map((item) => ({
        purchase_order_item_id: item.id,
        quantity: parseQuantity(quantities[item.id] ?? "0") ?? 0,
      }))
      .filter((item) => item.quantity > 0);

    receiptMutation.mutate(
      {
        purchase_order_id: order.id,
        warehouse_id: Number(warehouseId),
        receipt_date: todayIso(),
        items,
      },
      {
        onSuccess: (receipt) =>
          onDone(
            `Recepción ${receipt.code} registrada; el stock fue actualizado y la orden cambió de estado.`,
          ),
      },
    );
  }

  const serverMessage = errorMessage(receiptMutation.error);
  const visibleError = formError ?? serverMessage;

  return (
    <PurchasingDialog
      open
      title={`Recibir mercancía · ${order.code}`}
      subtitle="La recepción incrementa el stock en la bodega elegida y cierra la orden al completarse."
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose} className={secondaryButton}>
            Volver
          </button>
          <button
            type="button"
            onClick={handleReceive}
            disabled={receiptMutation.isPending || warehousesQuery.isPending}
            className={primaryButton}
          >
            {receiptMutation.isPending ? "Registrando…" : "Registrar recepción"}
          </button>
        </>
      }
    >
      <div>
        <label className={labelClass} htmlFor="receipt-warehouse">
          Bodega destino <span className="text-signal-600">*</span>
        </label>
        <select
          id="receipt-warehouse"
          className={fieldClass}
          value={warehouseId}
          onChange={(event) => setWarehouseId(event.currentTarget.value)}
        >
          <option value="">Selecciona una bodega activa</option>
          {warehouses.map((warehouse) => (
            <option key={warehouse.id} value={warehouse.id}>
              {warehouse.code} — {warehouse.name}
            </option>
          ))}
        </select>
        {warehousesQuery.isPending ? (
          <p className="mt-1 text-xs text-ink-500">Cargando bodegas…</p>
        ) : null}
        {!warehousesQuery.isPending && warehouses.length === 0 ? (
          <p className="mt-2 border-l-2 border-signal-500 bg-signal-100 px-3 py-2 text-xs font-medium text-signal-600">
            No hay bodegas activas. Activa una en inventario antes de recibir.
          </p>
        ) : null}
        {warehousesQuery.error === null ? null : (
          <p className="mt-2 border-l-2 border-signal-500 bg-signal-100 px-3 py-2 text-xs font-medium text-signal-600">
            No se pudieron cargar las bodegas: {warehousesQuery.error.message}
          </p>
        )}
      </div>

      <section aria-labelledby="receipt-lines-heading">
        <h3
          id="receipt-lines-heading"
          className="text-sm font-bold tracking-tight"
        >
          Cantidades a recibir
        </h3>
        <ul className="mt-2 divide-y divide-concrete-200 border border-concrete-200 bg-white">
          {order.items.map((item) => {
            const pending = pendingByItem.get(item.id) ?? 0;
            return (
              <li
                key={item.id}
                className="grid gap-2 px-3 py-2 sm:grid-cols-[1fr_7rem]"
              >
                <div className="min-w-0">
                  <span className="block truncate text-sm font-medium text-ink-950">
                    Producto #{item.product_id}
                  </span>
                  <span className="text-xs text-ink-500">
                    Ordenadas {item.quantity} · recibidas{" "}
                    {item.received_quantity} · pendientes {pending}
                  </span>
                </div>
                <div>
                  <label
                    className="sr-only"
                    htmlFor={`receipt-qty-${item.id}`}
                  >
                    Cantidad a recibir del producto #{item.product_id}
                  </label>
                  <input
                    id={`receipt-qty-${item.id}`}
                    className={fieldClass}
                    type="text"
                    inputMode="numeric"
                    value={quantities[item.id] ?? ""}
                    onChange={(event) =>
                      setQuantities((current) => ({
                        ...current,
                        [item.id]: event.currentTarget.value,
                      }))
                    }
                  />
                </div>
              </li>
            );
          })}
        </ul>
        <p className="mt-1 text-xs text-ink-500">
          Deja en 0 las líneas que no se reciben. No se permite superar el saldo
          pendiente (el backend rechaza la operación de forma atómica).
        </p>
      </section>

      {visibleError === null ? null : (
        <div
          role="alert"
          className="border-l-2 border-signal-500 bg-signal-100 px-3 py-2 text-sm font-medium text-signal-600"
        >
          <p>{visibleError}</p>
          {formError === null && serverMessage !== null ? (
            <p className="mt-1 font-normal">
              {errorHint(serverMessage) ??
                "Revisa los datos y vuelve a intentarlo."}
            </p>
          ) : null}
        </div>
      )}
    </PurchasingDialog>
  );
}

export function ReceiveOrderDialog({
  open,
  order,
  onClose,
  onDone,
}: OrderDialogProps) {
  if (!open || order === null) {
    return null;
  }
  return (
    <ReceiveOrderContent order={order} onClose={onClose} onDone={onDone} />
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
