import { useEffect, useMemo, useState } from "react";

import { useProducts, useWarehouses } from "../../api/inventory";
import {
  useCreateGoodsReceipt,
  usePurchaseOrders,
  useSuppliers,
} from "../../api/purchasing";
import type { PurchaseOrder } from "../../api/purchasing";
import { isReceivableOrderStatus } from "./constants";
import { errorHint, errorMessage } from "./errors";
import {
  computeLine,
  formatCents,
  formatDate,
  parseQuantity,
  todayIso,
} from "./format";
import PurchasingDialog from "./PurchasingDialog";

interface GoodsReceiptFormProps {
  open: boolean;
  /** OC preseleccionada desde la tabla de órdenes; si es `null`, se elige aquí. */
  order: PurchaseOrder | null;
  onClose: () => void;
  onDone: (message: string) => void;
}

interface ContentProps {
  preselectedOrder: PurchaseOrder | null;
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

/** Saldo pendiente de una línea de la OC. */
function pendingOf(quantity: number, receivedQuantity: number): number {
  return Math.max(0, quantity - receivedQuantity);
}

function GoodsReceiptFormContent({
  preselectedOrder,
  onClose,
  onDone,
}: ContentProps) {
  const [orderId, setOrderId] = useState(
    preselectedOrder === null ? "" : String(preselectedOrder.id),
  );
  const [warehouseId, setWarehouseId] = useState("");
  const [receiptDate, setReceiptDate] = useState(todayIso());
  const [receivedBy, setReceivedBy] = useState("");
  const [notes, setNotes] = useState("");
  const [quantities, setQuantities] = useState<Record<number, string>>({});
  const [formError, setFormError] = useState<string | null>(null);

  const ordersQuery = usePurchaseOrders({ limit: 200 });
  const warehousesQuery = useWarehouses({ active_only: true, limit: 200 });
  const productsQuery = useProducts({ limit: 200 });
  const suppliersQuery = useSuppliers({ limit: 200 });
  const receiptMutation = useCreateGoodsReceipt();

  const receivableOrders = (ordersQuery.data ?? []).filter(
    (order) =>
      isReceivableOrderStatus(order.status) &&
      order.items.some((item) => pendingOf(item.quantity, item.received_quantity) > 0),
  );

  const selectedOrder =
    preselectedOrder ??
    receivableOrders.find((order) => order.id === Number(orderId)) ??
    null;

  const warehouses = warehousesQuery.data ?? [];
  const productById = useMemo(
    () =>
      new Map(
        (productsQuery.data ?? []).map((product) => [product.id, product]),
      ),
    [productsQuery.data],
  );
  const supplierById = useMemo(
    () =>
      new Map(
        (suppliersQuery.data ?? []).map((supplier) => [supplier.id, supplier]),
      ),
    [suppliersQuery.data],
  );

  // Al elegir orden se precarga el saldo pendiente de cada línea, que es el
  // máximo que el backend permite recibir sin rechazar la operación.
  useEffect(() => {
    if (selectedOrder === null) {
      setQuantities({});
      return;
    }
    const initial: Record<number, string> = {};
    for (const item of selectedOrder.items) {
      initial[item.id] = String(pendingOf(item.quantity, item.received_quantity));
    }
    setQuantities(initial);
    setFormError(null);
  }, [selectedOrder]);

  useEffect(() => {
    if (warehouseId !== "" || warehouses.length !== 1) {
      return;
    }
    const only = warehouses[0];
    if (only !== undefined) {
      setWarehouseId(String(only.id));
    }
  }, [warehouses, warehouseId]);

  const totals = useMemo(() => {
    let units = 0;
    let cents = 0;
    if (selectedOrder !== null) {
      for (const item of selectedOrder.items) {
        const quantity = parseQuantity(quantities[item.id] ?? "0");
        if (quantity === null) {
          continue;
        }
        units += quantity;
        const unitPrice = Number(item.unit_price);
        const taxRate = Number(item.tax_rate);
        if (Number.isFinite(unitPrice) && Number.isFinite(taxRate)) {
          cents += computeLine(quantity, unitPrice, taxRate).totalCents;
        }
      }
    }
    return { units, cents };
  }, [quantities, selectedOrder]);

  const queryError =
    ordersQuery.error ??
    warehousesQuery.error ??
    productsQuery.error ??
    suppliersQuery.error;
  const serverMessage = errorMessage(receiptMutation.error);
  const visibleError = formError ?? serverMessage;

  function validate(): string | null {
    if (selectedOrder === null) {
      return "Selecciona una orden aprobada con saldo pendiente de recepción.";
    }
    if (!isReceivableOrderStatus(selectedOrder.status)) {
      return "Solo se reciben mercancías en órdenes APPROVED o PARTIALLY_RECEIVED.";
    }
    if (warehouseId === "") {
      return "Selecciona la bodega destino de la mercancía.";
    }
    if (receiptDate.trim() === "") {
      return "Indica la fecha física de recepción.";
    }
    if (receivedBy.trim().length > 100) {
      return "El responsable de la recepción no puede superar 100 caracteres.";
    }

    let hasQuantity = false;
    for (const item of selectedOrder.items) {
      const pending = pendingOf(item.quantity, item.received_quantity);
      const raw = quantities[item.id] ?? "0";
      if (raw.trim() === "" || raw.trim() === "0") {
        continue;
      }
      const quantity = parseQuantity(raw);
      if (quantity === null) {
        return `Línea ${item.id}: indica una cantidad entera mayor que cero.`;
      }
      if (quantity > pending) {
        return `Línea ${item.id}: quedan ${pending} unidades pendientes; recibir ${quantity} superaría el saldo.`;
      }
      hasQuantity = true;
    }
    if (!hasQuantity) {
      return "Indica al menos una cantidad mayor que cero para registrar la recepción.";
    }
    return null;
  }

  function handleSubmit() {
    if (selectedOrder === null) {
      setFormError("Selecciona una orden de compra antes de continuar.");
      return;
    }
    const message = validate();
    if (message !== null) {
      setFormError(message);
      return;
    }
    setFormError(null);

    const items = selectedOrder.items
      .map((item) => ({
        purchase_order_item_id: item.id,
        quantity: parseQuantity(quantities[item.id] ?? "0") ?? 0,
      }))
      .filter((item) => item.quantity > 0);
    const responsible = receivedBy.trim();

    receiptMutation.mutate(
      {
        purchase_order_id: selectedOrder.id,
        warehouse_id: Number(warehouseId),
        receipt_date: receiptDate,
        received_by: responsible === "" ? null : responsible,
        notes: notes.trim() === "" ? null : notes.trim(),
        items,
      },
      {
        onSuccess: (receipt) =>
          onDone(
            `Recepción ${receipt.code} registrada: ${totals.units} unidades ` +
              `ingresadas al stock y orden ${selectedOrder.code} actualizada.`,
          ),
      },
    );
  }

  return (
    <PurchasingDialog
      open
      title="Registrar recepción de mercancía"
      subtitle="La entrada impacta el stock de la bodega destino y actualiza las líneas recibidas de la OC."
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose} className={secondaryButton}>
            Cancelar
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={
              receiptMutation.isPending ||
              warehousesQuery.isPending ||
              ordersQuery.isPending
            }
            className={primaryButton}
          >
            {receiptMutation.isPending
              ? "Registrando…"
              : `Registrar recepción (${totals.units} und.)`}
          </button>
        </>
      }
    >
      {preselectedOrder === null ? (
        <div>
          <label className={labelClass} htmlFor="receipt-order">
            Orden de compra <span className="text-signal-600">*</span>
          </label>
          <select
            id="receipt-order"
            className={fieldClass}
            value={orderId}
            onChange={(event) => setOrderId(event.currentTarget.value)}
          >
            <option value="">Selecciona una orden aprobada</option>
            {receivableOrders.map((order) => (
              <option key={order.id} value={order.id}>
                {order.code} · {order.items.length} línea(s)
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-ink-500">
            Solo aparecen órdenes APPROVED o PARTIALLY_RECEIVED con saldo
            pendiente.
          </p>
          {ordersQuery.isPending ? (
            <p className="mt-1 text-xs text-ink-500">Cargando órdenes…</p>
          ) : null}
          {!ordersQuery.isPending && receivableOrders.length === 0 ? (
            <p className="mt-2 border-l-2 border-clay-600 bg-clay-100 px-3 py-2 text-xs font-medium text-clay-600">
              No hay órdenes aprobadas con saldo pendiente. Aprueba una orden
              antes de recibir mercancía.
            </p>
          ) : null}
        </div>
      ) : (
        <div className="border border-concrete-200 bg-white px-3 py-2.5 text-sm">
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-ink-500">
            Orden seleccionada
          </p>
          <p className="mt-1 font-semibold tabular-nums">
            {preselectedOrder.code}
          </p>
          <p className="mt-0.5 text-xs text-ink-500">
            {supplierById.get(preselectedOrder.supplier_id)?.company_name ??
              `Proveedor #${preselectedOrder.supplier_id}`}{" "}
            · emitida el {formatDate(preselectedOrder.issue_date)}
          </p>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-3">
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
            <option value="">Selecciona una bodega</option>
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
            <p className="mt-1 text-xs font-medium text-signal-600">
              No hay bodegas activas en inventario.
            </p>
          ) : null}
        </div>
        <div>
          <label className={labelClass} htmlFor="receipt-date">
            Fecha de recepción <span className="text-signal-600">*</span>
          </label>
          <input
            id="receipt-date"
            type="date"
            className={fieldClass}
            value={receiptDate}
            onChange={(event) => setReceiptDate(event.currentTarget.value)}
          />
        </div>
        <div>
          <label className={labelClass} htmlFor="receipt-by">
            Recibido por <span className="font-normal text-ink-500">(opcional)</span>
          </label>
          <input
            id="receipt-by"
            type="text"
            maxLength={100}
            className={fieldClass}
            value={receivedBy}
            onChange={(event) => setReceivedBy(event.currentTarget.value)}
            placeholder="Se usa tu usuario si se deja vacío"
          />
        </div>
      </div>

      <section aria-labelledby="goods-receipt-lines">
        <div className="flex items-end justify-between gap-3">
          <div>
            <h3
              id="goods-receipt-lines"
              className="text-sm font-bold tracking-tight"
            >
              Cantidades recibidas
            </h3>
            <p className="mt-0.5 text-xs text-ink-500">
              Precargadas con el saldo pendiente. No se permite sobre-recepción.
            </p>
          </div>
          <span className="shrink-0 text-xs font-semibold tabular-nums text-ink-500">
            {totals.units} und. · {formatCents(totals.cents)}
          </span>
        </div>

        {selectedOrder === null ? (
          <p className="mt-3 border border-dashed border-concrete-200 bg-white px-4 py-6 text-center text-sm text-ink-500">
            Selecciona una orden para ver sus líneas pendientes.
          </p>
        ) : (
          <ul className="mt-3 divide-y divide-concrete-200 border border-concrete-200 bg-white">
            {selectedOrder.items.map((item) => {
              const pending = pendingOf(item.quantity, item.received_quantity);
              const product = productById.get(item.product_id);
              const raw = quantities[item.id] ?? "0";
              const parsed = parseQuantity(raw);
              const exceeds = parsed !== null && parsed > pending;
              return (
                <li
                  key={item.id}
                  className="grid gap-2 px-3 py-2.5 sm:grid-cols-[1fr_7rem]"
                >
                  <div className="min-w-0">
                    <span className="block truncate text-sm font-medium text-ink-950">
                      {product === undefined
                        ? `Producto #${item.product_id}`
                        : `${product.sku} — ${product.name}`}
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
                      Cantidad a recibir de {product?.name ?? `producto #${item.product_id}`}
                    </label>
                    <input
                      id={`receipt-qty-${item.id}`}
                      type="text"
                      inputMode="numeric"
                      value={raw}
                      onChange={(event) =>
                        setQuantities((current) => ({
                          ...current,
                          [item.id]: event.currentTarget.value,
                        }))
                      }
                      className={[
                        fieldClass,
                        exceeds ? "border-signal-500 text-signal-600" : "",
                      ].join(" ")}
                    />
                    {exceeds ? (
                      <span className="mt-1 block text-[0.6875rem] font-medium text-signal-600">
                        Máximo {pending} unidades
                      </span>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
        <p className="mt-1 text-xs text-ink-500">
          Deja en 0 las líneas que no se reciben en esta entrega.
        </p>
      </section>

      <div>
        <label className={labelClass} htmlFor="receipt-notes">
          Observaciones <span className="font-normal text-ink-500">(opcional)</span>
        </label>
        <textarea
          id="receipt-notes"
          rows={2}
          value={notes}
          onChange={(event) => setNotes(event.currentTarget.value)}
          placeholder="Ej. mercancía recibida en buen estado"
          className={fieldClass}
        />
      </div>

      {queryError === null ? null : (
        <p className="border-l-2 border-signal-500 bg-signal-100 px-3 py-2 text-xs font-medium text-signal-600">
          Algunos datos de apoyo no se pudieron cargar: {queryError.message}
        </p>
      )}

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

/**
 * Registro de entrada de mercancía. Se monta solo al abrirse para no ejecutar
 * las consultas de apoyo en cada render de la vista que lo invoca.
 */
export default function GoodsReceiptForm({
  open,
  order,
  onClose,
  onDone,
}: GoodsReceiptFormProps) {
  if (!open) {
    return null;
  }
  return (
    <GoodsReceiptFormContent
      preselectedOrder={order}
      onClose={onClose}
      onDone={onDone}
    />
  );
}
