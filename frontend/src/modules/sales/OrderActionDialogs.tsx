import { useEffect, useMemo, useState } from "react";

import { useProducts, useStock, useWarehouses } from "../../api/inventory";
import type { StockFilters } from "../../api/inventory";
import {
  useCancelSalesOrder,
  useConfirmSalesOrder,
  useInvoices,
} from "../../api/sales";
import type {
  Customer,
  InvoiceFilters,
  SalesOrder,
} from "../../api/sales";
import { isCancellableOrderStatus } from "./constants";
import { errorHint, errorMessage } from "./errors";
import { formatMoney } from "./format";
import SalesDialog from "./SalesDialog";

function toCents(value: string | number): number {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? Math.round(parsed * 100) : 0;
}

interface OrderDialogProps {
  open: boolean;
  order: SalesOrder | null;
  onClose: () => void;
  onDone: (message: string) => void;
}

interface ConfirmContentProps {
  order: SalesOrder;
  customer: Customer | null;
  onClose: () => void;
  onDone: (message: string) => void;
}

function ConfirmOrderContent({
  order,
  customer,
  onClose,
  onDone,
}: ConfirmContentProps) {
  const [warehouseId, setWarehouseId] = useState("");

  const warehousesQuery = useWarehouses({ active_only: true, limit: 200 });
  const warehouses = warehousesQuery.data ?? [];

  // Si solo hay una bodega activa se preselecciona; con varias el usuario
  // debe elegir para que el descuento sea explícito.
  useEffect(() => {
    if (warehouseId !== "") {
      return;
    }
    const only = warehouses.length === 1 ? warehouses[0] : undefined;
    if (only !== undefined) {
      setWarehouseId(String(only.id));
    }
  }, [warehouses, warehouseId]);

  const selectedWarehouseId =
    warehouseId === "" ? null : Number(warehouseId);

  const invoiceFilters: InvoiceFilters = {
    customer_id: order.customer_id,
    status: "ISSUED",
    limit: 200,
  };
  const invoicesQuery = useInvoices(invoiceFilters);

  const stockFilters: StockFilters = { limit: 500 };
  if (selectedWarehouseId !== null) {
    stockFilters.warehouse_id = selectedWarehouseId;
  }
  const stockQuery = useStock(stockFilters);

  const productsQuery = useProducts({ limit: 200 });
  const confirmMutation = useConfirmSalesOrder();

  const productNames = useMemo(() => {
    const names = new Map<number, string>();
    for (const product of productsQuery.data ?? []) {
      names.set(product.id, `${product.sku} — ${product.name}`);
    }
    return names;
  }, [productsQuery.data]);

  const orderCents = toCents(order.total);
  const pendingCents = (invoicesQuery.data ?? []).reduce(
    (total, invoice) => total + toCents(invoice.balance_due),
    0,
  );
  const limitCents =
    customer === null ? null : toCents(customer.credit_limit);
  const availableCents =
    limitCents === null ? null : limitCents - pendingCents;
  const creditReady = !invoicesQuery.isPending && invoicesQuery.error === null;
  const exceedsCredit =
    creditReady && availableCents !== null && orderCents > availableCents;
  const creditPending = customer !== null && invoicesQuery.isPending;
  const inactiveCustomer = customer !== null && !customer.is_active;

  const requiredByProduct = useMemo(() => {
    const required = new Map<number, number>();
    for (const item of order.items) {
      required.set(
        item.product_id,
        (required.get(item.product_id) ?? 0) + item.quantity,
      );
    }
    return required;
  }, [order.items]);

  const stockByProduct = useMemo(() => {
    const levels = new Map<number, number>();
    for (const level of stockQuery.data ?? []) {
      levels.set(level.product_id, level.quantity);
    }
    return levels;
  }, [stockQuery.data]);

  const stockReady =
    selectedWarehouseId !== null &&
    !stockQuery.isPending &&
    stockQuery.error === null;
  const stockPending =
    selectedWarehouseId !== null && stockQuery.isPending;

  const shortages = useMemo(() => {
    if (!stockReady) {
      return [];
    }
    return [...requiredByProduct.entries()]
      .map(([productId, required]) => ({
        productId,
        required,
        available: stockByProduct.get(productId) ?? 0,
      }))
      .filter((line) => line.available < line.required);
  }, [requiredByProduct, stockByProduct, stockReady]);

  const noWarehouse = !warehousesQuery.isPending && warehouses.length === 0;
  const needsWarehouseChoice = warehouses.length > 1 && warehouseId === "";
  const stockBlocked = stockReady && shortages.length > 0;

  const mutationMessage = errorMessage(confirmMutation.error);
  const mutationHint =
    mutationMessage === null ? null : errorHint(mutationMessage);
  const visibleError = mutationMessage;

  const submitDisabled =
    noWarehouse ||
    needsWarehouseChoice ||
    inactiveCustomer ||
    exceedsCredit ||
    stockBlocked ||
    creditPending ||
    stockPending ||
    confirmMutation.isPending;

  function handleConfirm() {
    confirmMutation.mutate(
      { orderId: order.id, warehouseId: selectedWarehouseId },
      {
        onSuccess: (confirmed) =>
          onDone(
            `Pedido ${confirmed.code} confirmado; stock descontado de la bodega seleccionada.`,
          ),
      },
    );
  }

  return (
    <SalesDialog
      open
      title={`Confirmar pedido ${order.code}`}
      subtitle="La confirmación valida el crédito y descuenta inventario en una sola transacción."
      onClose={onClose}
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="border border-concrete-200 px-4 py-2 text-sm font-semibold text-ink-700 hover:border-ink-500 hover:text-ink-950"
          >
            Volver
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={submitDisabled}
            className="bg-signal-500 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-signal-600 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {confirmMutation.isPending ? "Confirmando…" : "Confirmar pedido"}
          </button>
        </>
      }
    >
      <dl className="grid grid-cols-2 gap-px border border-concrete-200 bg-concrete-200 text-sm">
        <div className="bg-white px-3 py-2.5">
          <dt className="text-xs font-semibold text-ink-500">Cliente</dt>
          <dd className="mt-0.5 font-semibold">
            {customer === null
              ? `Cliente #${order.customer_id}`
              : customer.company_name}
          </dd>
        </div>
        <div className="bg-white px-3 py-2.5">
          <dt className="text-xs font-semibold text-ink-500">Total del pedido</dt>
          <dd className="mt-0.5 font-semibold tabular-nums">
            {formatMoney(order.total)}
          </dd>
        </div>
      </dl>

      {inactiveCustomer ? (
        <p
          role="alert"
          className="border-l-2 border-signal-500 bg-signal-100 px-3 py-2 text-sm font-semibold text-signal-600"
        >
          El cliente está inactivo. Reactívalo antes de confirmar el pedido; el
          backend rechazará la operación.
        </p>
      ) : null}

      <section aria-labelledby="confirm-credit-heading">
        <h3
          id="confirm-credit-heading"
          className="text-sm font-bold tracking-tight"
        >
          Cupo de crédito
        </h3>
        {customer === null ? (
          <p className="mt-2 border-l-2 border-clay-600 bg-clay-100 px-3 py-2 text-xs font-medium text-clay-600">
            No se pudo precargar el cupo del cliente; el servidor validará el
            crédito al confirmar.
          </p>
        ) : invoicesQuery.error !== null ? (
          <p className="mt-2 border-l-2 border-clay-600 bg-clay-100 px-3 py-2 text-xs font-medium text-clay-600">
            No se pudo calcular la deuda vigente ({invoicesQuery.error.message}).
            El servidor validará el crédito al confirmar.
          </p>
        ) : (
          <dl className="mt-2 space-y-1 text-sm">
            <div className="flex justify-between gap-4">
              <dt className="text-ink-500">Límite</dt>
              <dd className="tabular-nums">
                {formatMoney(customer.credit_limit)}
              </dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-ink-500">Deuda vigente (facturas emitidas)</dt>
              <dd className="tabular-nums">{formatMoney(pendingCents / 100)}</dd>
            </div>
            <div className="flex justify-between gap-4 border-t border-concrete-200 pt-1">
              <dt className="font-semibold">Disponible</dt>
              <dd
                className={[
                  "font-bold tabular-nums",
                  availableCents !== null && availableCents < 0
                    ? "text-signal-600"
                    : "text-ink-950",
                ].join(" ")}
              >
                {availableCents === null
                  ? "—"
                  : formatMoney(availableCents / 100)}
              </dd>
            </div>
          </dl>
        )}

        {invoicesQuery.isPending && customer !== null ? (
          <p className="mt-1 text-xs text-ink-500">
            Calculando deuda vigente…
          </p>
        ) : null}

        {exceedsCredit ? (
          <p
            role="alert"
            className="mt-2 border-l-2 border-signal-500 bg-signal-100 px-3 py-2 text-xs font-semibold text-signal-600"
          >
            El total del pedido supera el cupo disponible. Reduce el pedido,
            registra un pago o amplía el límite antes de confirmar.
          </p>
        ) : null}
      </section>

      <section aria-labelledby="confirm-warehouse-heading">
        <h3
          id="confirm-warehouse-heading"
          className="text-sm font-bold tracking-tight"
        >
          Bodega de despacho
        </h3>
        {warehousesQuery.isPending ? (
          <p className="mt-1 text-xs text-ink-500">Cargando bodegas…</p>
        ) : warehousesQuery.error !== null ? (
          <p className="mt-2 border-l-2 border-signal-500 bg-signal-100 px-3 py-2 text-xs font-medium text-signal-600">
            No se pudieron cargar las bodegas: {warehousesQuery.error.message}
          </p>
        ) : noWarehouse ? (
          <p
            role="alert"
            className="mt-2 border-l-2 border-signal-500 bg-signal-100 px-3 py-2 text-xs font-semibold text-signal-600"
          >
            No hay bodegas activas. Activa una bodega en inventario antes de
            confirmar pedidos.
          </p>
        ) : (
          <>
            <label className="sr-only" htmlFor="confirm-warehouse">
              Bodega de despacho
            </label>
            <select
              id="confirm-warehouse"
              value={warehouseId}
              onChange={(event) => setWarehouseId(event.currentTarget.value)}
              className="mt-2 w-full border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-950 focus:border-ink-950"
            >
              <option value="">Selecciona una bodega</option>
              {warehouses.map((warehouse) => (
                <option key={warehouse.id} value={warehouse.id}>
                  {warehouse.code} — {warehouse.name}
                </option>
              ))}
            </select>
            {needsWarehouseChoice ? (
              <p className="mt-1 text-xs font-medium text-clay-600">
                Hay varias bodegas activas; elige de cuál se descuenta el stock.
              </p>
            ) : null}
          </>
        )}
      </section>

      <section aria-labelledby="confirm-stock-heading">
        <h3
          id="confirm-stock-heading"
          className="text-sm font-bold tracking-tight"
        >
          Existencias requeridas
        </h3>
        {selectedWarehouseId === null ? (
          <p className="mt-1 text-xs text-ink-500">
            Selecciona una bodega para comparar las cantidades con el stock
            disponible.
          </p>
        ) : stockQuery.isPending ? (
          <p className="mt-1 text-xs text-ink-500">Consultando existencias…</p>
        ) : stockQuery.error !== null ? (
          <p className="mt-2 border-l-2 border-clay-600 bg-clay-100 px-3 py-2 text-xs font-medium text-clay-600">
            No se pudo consultar el stock ({stockQuery.error.message}). El
            servidor validará las existencias al confirmar.
          </p>
        ) : (
          <ul className="mt-2 divide-y divide-concrete-100 border border-concrete-200 bg-white text-sm">
            {[...requiredByProduct.entries()].map(([productId, required]) => {
              const available = stockByProduct.get(productId) ?? 0;
              const short = available < required;
              return (
                <li
                  key={productId}
                  className="flex items-start justify-between gap-4 px-3 py-2"
                >
                  <span className="min-w-0">
                    <span className="block truncate font-medium">
                      {productNames.get(productId) ?? `Producto #${productId}`}
                    </span>
                    <span className="text-xs text-ink-500">
                      Solicitado: {required}
                    </span>
                  </span>
                  <span
                    className={[
                      "shrink-0 text-right text-xs font-semibold tabular-nums",
                      short ? "text-signal-600" : "text-pine-600",
                    ].join(" ")}
                  >
                    {available} disponibles
                  </span>
                </li>
              );
            })}
          </ul>
        )}

        {stockBlocked ? (
          <p
            role="alert"
            className="mt-2 border-l-2 border-signal-500 bg-signal-100 px-3 py-2 text-xs font-semibold text-signal-600"
          >
            Stock insuficiente en la bodega seleccionada. Repón inventario,
            elige otra bodega o reduce las cantidades; la confirmación no
            descontará nada parcialmente.
          </p>
        ) : null}
      </section>

      {visibleError === null ? null : (
        <div
          role="alert"
          className="border-l-2 border-signal-500 bg-signal-100 px-3 py-2 text-sm font-medium text-signal-600"
        >
          <p>{visibleError}</p>
          {mutationHint === null ? null : (
            <p className="mt-1 font-normal">{mutationHint}</p>
          )}
        </div>
      )}
    </SalesDialog>
  );
}

/** Confirma un pedido: valida crédito y stock, y descuenta la bodega elegida. */
export function ConfirmOrderDialog({
  open,
  order,
  customer,
  onClose,
  onDone,
}: OrderDialogProps & { customer: Customer | null }) {
  if (!open || order === null) {
    return null;
  }
  return (
    <ConfirmOrderContent
      order={order}
      customer={customer}
      onClose={onClose}
      onDone={onDone}
    />
  );
}

interface CancelContentProps {
  order: SalesOrder;
  onClose: () => void;
  onDone: (message: string) => void;
}

function CancelOrderContent({ order, onClose, onDone }: CancelContentProps) {
  const [reason, setReason] = useState("");
  const invoicesQuery = useInvoices({ sales_order_id: order.id, limit: 200 });
  const cancelMutation = useCancelSalesOrder();

  const invoices = invoicesQuery.data ?? [];
  const hasInvoices = invoices.length > 0;
  const cancellable = isCancellableOrderStatus(order.status);
  const mutationMessage = errorMessage(cancelMutation.error);
  const mutationHint =
    mutationMessage === null ? null : errorHint(mutationMessage);

  const submitDisabled =
    !cancellable || hasInvoices || cancelMutation.isPending;

  function handleCancel() {
    const trimmed = reason.trim();
    cancelMutation.mutate(
      { orderId: order.id, reason: trimmed === "" ? null : trimmed },
      {
        onSuccess: (cancelled) =>
          onDone(
            order.status === "CONFIRMED"
              ? `Pedido ${cancelled.code} cancelado; el stock despachado fue revertido.`
              : `Pedido ${cancelled.code} cancelado.`,
          ),
      },
    );
  }

  return (
    <SalesDialog
      open
      title={`Cancelar pedido ${order.code}`}
      subtitle="La cancelación es definitiva y deja el documento en estado CANCELLED."
      onClose={onClose}
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="border border-concrete-200 px-4 py-2 text-sm font-semibold text-ink-700 hover:border-ink-500 hover:text-ink-950"
          >
            Volver
          </button>
          <button
            type="button"
            onClick={handleCancel}
            disabled={submitDisabled}
            className="bg-signal-500 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-signal-600 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {cancelMutation.isPending ? "Cancelando…" : "Cancelar pedido"}
          </button>
        </>
      }
    >
      {!cancellable ? (
        <p
          role="alert"
          className="border-l-2 border-signal-500 bg-signal-100 px-3 py-2 text-sm font-semibold text-signal-600"
        >
          Un pedido en estado {order.status} no puede cancelarse. Si ya fue
          entregado, corrige la operación con una nota crédito sobre la factura.
        </p>
      ) : order.status === "CONFIRMED" ? (
        <p className="border-l-2 border-clay-600 bg-clay-100 px-3 py-2 text-sm font-medium text-clay-600">
          Este pedido ya descontó inventario. Al cancelarlo se registrarán
          movimientos INBOUND de contrapartida por cada línea despachada.
        </p>
      ) : (
        <p className="text-sm text-ink-700">
          El pedido aún no descuenta inventario; solo cambiará de estado.
        </p>
      )}

      {invoicesQuery.error !== null ? (
        <p className="border-l-2 border-clay-600 bg-clay-100 px-3 py-2 text-xs font-medium text-clay-600">
          No se pudieron consultar las facturas asociadas
          ({invoicesQuery.error.message}). El servidor bloqueará la cancelación
          si existe alguna.
        </p>
      ) : hasInvoices ? (
        <div
          role="alert"
          className="border-l-2 border-signal-500 bg-signal-100 px-3 py-2 text-sm font-medium text-signal-600"
        >
          <p className="font-semibold">
            El pedido tiene {invoices.length} factura
            {invoices.length === 1 ? "" : "s"} asociada
            {invoices.length === 1 ? "" : "s"}.
          </p>
          <p className="mt-1">
            Anula la factura (VOID) o emite una nota crédito en lugar de
            cancelar el pedido.
          </p>
        </div>
      ) : invoicesQuery.isPending ? (
        <p className="text-xs text-ink-500">Verificando facturas asociadas…</p>
      ) : null}

      <div>
        <label
          className="mb-1.5 block text-xs font-semibold text-ink-700"
          htmlFor="cancel-reason"
        >
          Motivo{" "}
          <span className="font-normal text-ink-500">(opcional, máx. 500)</span>
        </label>
        <textarea
          id="cancel-reason"
          rows={3}
          maxLength={500}
          value={reason}
          onChange={(event) => setReason(event.currentTarget.value)}
          placeholder="Ej. el cliente desistió de la compra"
          className="w-full border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-950 placeholder:text-concrete-400 focus:border-ink-950"
        />
        <p className="mt-1 text-xs text-ink-500">
          El motivo se guarda en las notas de los movimientos de reversión.
        </p>
      </div>

      {mutationMessage === null ? null : (
        <div
          role="alert"
          className="border-l-2 border-signal-500 bg-signal-100 px-3 py-2 text-sm font-medium text-signal-600"
        >
          <p>{mutationMessage}</p>
          {mutationHint === null ? null : (
            <p className="mt-1 font-normal">{mutationHint}</p>
          )}
        </div>
      )}
    </SalesDialog>
  );
}

/** Cancela un pedido; bloquea si ya tiene facturas asociadas. */
export function CancelOrderDialog({
  open,
  order,
  onClose,
  onDone,
}: OrderDialogProps) {
  if (!open || order === null) {
    return null;
  }
  return (
    <CancelOrderContent order={order} onClose={onClose} onDone={onDone} />
  );
}
