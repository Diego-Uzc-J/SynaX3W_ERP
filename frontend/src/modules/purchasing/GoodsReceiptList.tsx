import {
  Fragment,
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
} from "react";
import { Link, useNavigate } from "react-router-dom";

import { useWarehouses } from "../../api/inventory";
import {
  useGoodsReceipts,
  usePurchaseOrders,
  useSuppliers,
} from "../../api/purchasing";
import type { GoodsReceipt } from "../../api/purchasing";
import { formatDate, formatMoney, todayIso } from "./format";
import GoodsReceiptForm from "./GoodsReceiptForm";
import PurchasingTabs from "./PurchasingTabs";

const PAGE_SIZE = 12;

interface Feedback {
  tone: "success" | "error";
  text: string;
}

/** HISTORIAL DE RECEPCIONES — solo lectura; las recepciones son inmutables. */
export default function GoodsReceiptList() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [orderFilter, setOrderFilter] = useState("all");
  const [warehouseFilter, setWarehouseFilter] = useState("all");
  const [page, setPage] = useState(0);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  const deferredSearch = useDeferredValue(search.trim().toLowerCase());

  const receiptsQuery = useGoodsReceipts({ limit: 200 });
  const ordersQuery = usePurchaseOrders({ limit: 200 });
  const warehousesQuery = useWarehouses({ limit: 200 });
  const suppliersQuery = useSuppliers({ limit: 200 });

  useEffect(() => {
    setPage(0);
  }, [deferredSearch, orderFilter, warehouseFilter]);

  const receipts = receiptsQuery.data ?? [];
  const orders = ordersQuery.data ?? [];
  const warehouses = warehousesQuery.data ?? [];
  const suppliers = suppliersQuery.data ?? [];

  const orderById = useMemo(
    () => new Map(orders.map((order) => [order.id, order])),
    [orders],
  );
  const warehouseById = useMemo(
    () => new Map(warehouses.map((warehouse) => [warehouse.id, warehouse])),
    [warehouses],
  );
  const supplierById = useMemo(
    () => new Map(suppliers.map((supplier) => [supplier.id, supplier])),
    [suppliers],
  );

  const filtered = receipts.filter((receipt) => {
    if (orderFilter !== "all" && String(receipt.purchase_order_id) !== orderFilter) {
      return false;
    }
    if (warehouseFilter !== "all" && String(receipt.warehouse_id) !== warehouseFilter) {
      return false;
    }
    if (deferredSearch === "") {
      return true;
    }
    const haystack = [
      receipt.code,
      receipt.received_by ?? "",
      receipt.notes ?? "",
      orderById.get(receipt.purchase_order_id)?.code ?? "",
    ]
      .join(" ")
      .toLowerCase();
    return haystack.includes(deferredSearch);
  });

  const pageItems = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const totalUnits = filtered.reduce(
    (sum, receipt) =>
      sum + receipt.items.reduce((lineSum, item) => lineSum + item.quantity, 0),
    0,
  );
  const distinctOrders = new Set(
    filtered.map((receipt) => receipt.purchase_order_id),
  ).size;
  const hasFilters =
    deferredSearch !== "" || orderFilter !== "all" || warehouseFilter !== "all";

  function resetFilters() {
    setSearch("");
    setOrderFilter("all");
    setWarehouseFilter("all");
  }

  function handleDone(message: string) {
    setFeedback({ tone: "success", text: message });
    setFormOpen(false);
  }

  return (
    <div className="mx-auto w-full max-w-[1440px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
      <header className="flex flex-col gap-6 border-b-2 border-ink-950 pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-signal-600">
            Entrada de mercancía
          </p>
          <h1 className="mt-2 text-4xl font-extrabold tracking-tight sm:text-5xl">
            Recepciones
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-ink-700">
            Cada recepción incrementa el stock de la bodega destino y actualiza
            las cantidades recibidas de la orden. Los documentos son inmutables.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setFormOpen(true)}
          className="inline-flex shrink-0 items-center justify-center gap-2 bg-signal-500 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-signal-600"
        >
          <span aria-hidden="true" className="text-lg leading-none">
            +
          </span>
          Nueva recepción
        </button>
      </header>

      <PurchasingTabs />

      {feedback === null ? null : (
        <div
          role="status"
          className="mt-5 flex items-start justify-between gap-4 border border-pine-600/30 bg-pine-100 px-4 py-3 text-sm font-medium text-pine-600"
        >
          <p>{feedback.text}</p>
          <button
            type="button"
            onClick={() => setFeedback(null)}
            className="text-base leading-none hover:text-ink-950"
            aria-label="Cerrar aviso"
          >
            ×
          </button>
        </div>
      )}

      <dl className="mt-6 grid grid-cols-2 divide-x divide-concrete-200 border border-concrete-200 bg-white sm:grid-cols-3">
        <div className="px-4 py-3">
          <dt className="text-xs font-semibold text-ink-500">Recepciones</dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums">
            {filtered.length}
          </dd>
        </div>
        <div className="px-4 py-3">
          <dt className="text-xs font-semibold text-ink-500">Unidades ingresadas</dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums">
            {totalUnits}
          </dd>
        </div>
        <div className="col-span-2 border-t border-concrete-200 px-4 py-3 sm:col-span-1 sm:border-t-0">
          <dt className="text-xs font-semibold text-ink-500">Órdenes afectadas</dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums">
            {distinctOrders}
          </dd>
        </div>
      </dl>

      <div className="flex flex-col gap-3 py-5 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-1 flex-col gap-2 sm:flex-row">
          <div className="flex flex-1 border border-concrete-200 bg-white focus-within:border-ink-950">
            <label className="sr-only" htmlFor="receipt-search">
              Buscar recepciones
            </label>
            <input
              id="receipt-search"
              type="search"
              value={search}
              onChange={(event) => setSearch(event.currentTarget.value)}
              placeholder="Buscar por código, responsable u orden"
              className="min-w-0 flex-1 px-3 py-2 text-sm placeholder:text-concrete-400 focus:outline-none"
            />
          </div>
          <label className="sr-only" htmlFor="receipt-order-filter">
            Filtrar por orden de compra
          </label>
          <select
            id="receipt-order-filter"
            value={orderFilter}
            onChange={(event) => setOrderFilter(event.currentTarget.value)}
            className="max-w-full border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-700 sm:max-w-xs"
          >
            <option value="all">Todas las órdenes</option>
            {orders.map((order) => (
              <option key={order.id} value={order.id}>
                {order.code}
              </option>
            ))}
          </select>
          <label className="sr-only" htmlFor="receipt-warehouse-filter">
            Filtrar por bodega
          </label>
          <select
            id="receipt-warehouse-filter"
            value={warehouseFilter}
            onChange={(event) => setWarehouseFilter(event.currentTarget.value)}
            className="max-w-full border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-700 sm:max-w-xs"
          >
            <option value="all">Todas las bodegas</option>
            {warehouses.map((warehouse) => (
              <option key={warehouse.id} value={warehouse.id}>
                {warehouse.code} — {warehouse.name}
              </option>
            ))}
          </select>
        </div>
        <p className="text-xs text-ink-500" aria-live="polite">
          {filtered.length} recepción{filtered.length === 1 ? "" : "es"}
          {receiptsQuery.isFetching ? " · actualizando" : ""}
        </p>
      </div>

      {receiptsQuery.error !== null ? (
        <div className="border border-signal-500/40 bg-signal-100 px-5 py-6">
          <p className="text-sm font-semibold text-signal-600">
            No se pudo cargar el historial de recepciones.
          </p>
          <p className="mt-1 text-sm text-ink-700">{receiptsQuery.error.message}</p>
          <button
            type="button"
            onClick={() => void receiptsQuery.refetch()}
            className="mt-4 border border-signal-500 px-3 py-1.5 text-sm font-semibold text-signal-600 hover:bg-signal-500 hover:text-white"
          >
            Reintentar
          </button>
        </div>
      ) : receiptsQuery.isPending ? (
        <div className="border border-concrete-200 bg-white">
          {[0, 1, 2, 3].map((row) => (
            <div
              key={row}
              className="flex items-center gap-6 border-b border-concrete-100 px-4 py-4 last:border-b-0"
            >
              <div className="h-4 w-1/4 animate-pulse bg-concrete-100" />
              <div className="h-4 w-1/3 animate-pulse bg-concrete-100" />
              <div className="h-4 w-1/5 animate-pulse bg-concrete-100" />
            </div>
          ))}
        </div>
      ) : pageItems.length === 0 ? (
        <div className="border border-dashed border-concrete-200 bg-white px-6 py-16 text-center">
          <p className="text-lg font-semibold">
            {hasFilters
              ? "No hay recepciones que coincidan con los filtros."
              : "Todavía no se ha recibido mercancía."}
          </p>
          <p className="mx-auto mt-2 max-w-sm text-sm text-ink-500">
            {hasFilters
              ? "Cambia la orden, la bodega o el texto buscado."
              : "Aprueba una orden de compra para registrar la primera entrada."}
          </p>
          <button
            type="button"
            onClick={hasFilters ? resetFilters : () => setFormOpen(true)}
            className="mt-5 border border-ink-950 px-4 py-2 text-sm font-semibold hover:bg-ink-950 hover:text-concrete-50"
          >
            {hasFilters ? "Limpiar filtros" : "Registrar una recepción"}
          </button>
        </div>
      ) : (
        <div className="border border-concrete-200 bg-white">
          <div className="relative overflow-x-auto">
            <table className="w-full min-w-[1040px] border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-concrete-200 text-xs font-semibold text-ink-500">
                  <th scope="col" className="px-4 py-3">
                    Recepción
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Orden / proveedor
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Bodega destino
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Fecha
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Recibido por
                  </th>
                  <th scope="col" className="px-4 py-3 text-right">
                    Unidades
                  </th>
                  <th scope="col" className="px-4 py-3 text-right">
                    <span className="sr-only">Acciones</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {pageItems.map((receipt: GoodsReceipt) => {
                  const order = orderById.get(receipt.purchase_order_id);
                  const warehouse = warehouseById.get(receipt.warehouse_id);
                  const supplier =
                    order === undefined
                      ? undefined
                      : supplierById.get(order.supplier_id);
                  const units = receipt.items.reduce(
                    (sum, item) => sum + item.quantity,
                    0,
                  );
                  const isExpanded = expandedId === receipt.id;
                  return (
                    <Fragment key={receipt.id}>
                      <tr className="border-b border-concrete-100 hover:bg-concrete-50">
                        <td className="px-4 py-3">
                          <button
                            type="button"
                            onClick={() =>
                              setExpandedId(isExpanded ? null : receipt.id)
                            }
                            aria-expanded={isExpanded}
                            className="font-semibold tabular-nums text-ink-950 underline-offset-2 hover:underline"
                          >
                            {receipt.code}
                          </button>
                          <span className="mt-0.5 block text-xs text-ink-500">
                            {receipt.items.length} línea
                            {receipt.items.length === 1 ? "" : "s"} ·{" "}
                            {isExpanded ? "ocultar" : "ver detalle"}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span className="block font-medium tabular-nums">
                            {order?.code ?? `OC #${receipt.purchase_order_id}`}
                          </span>
                          <span className="mt-0.5 block max-w-[220px] truncate text-xs text-ink-500">
                            {supplier?.company_name ?? "Proveedor no disponible"}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-xs text-ink-700">
                          {warehouse?.code ?? `Bodega #${receipt.warehouse_id}`}
                          <span className="mt-0.5 block text-ink-500">
                            {warehouse?.name ?? "—"}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-xs text-ink-700">
                          {formatDate(receipt.receipt_date)}
                          <span className="mt-0.5 block text-ink-500">
                            Registrada {receipt.created_at.slice(0, 10)}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-xs text-ink-700">
                          {receipt.received_by ?? "—"}
                        </td>
                        <td className="px-4 py-3 text-right font-semibold tabular-nums">
                          {units}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <button
                            type="button"
                            onClick={() =>
                              navigate(
                                `/purchasing/bills?new=1&receipt=${receipt.id}`,
                              )
                            }
                            className="border border-concrete-200 px-2 py-1 text-[0.6875rem] font-semibold text-ink-700 hover:border-ink-950 hover:text-ink-950"
                          >
                            Facturar
                          </button>
                        </td>
                      </tr>
                      {isExpanded ? (
                        <tr
                          key={`${receipt.id}-detail`}
                          className="border-b border-concrete-100 bg-concrete-50"
                        >
                          <td colSpan={7} className="px-4 py-3">
                            {receipt.notes === null ? null : (
                              <p className="mb-2 text-xs italic text-ink-700">
                                “{receipt.notes}”
                              </p>
                            )}
                            <ul className="divide-y divide-concrete-200 border border-concrete-200 bg-white">
                              {receipt.items.map((item) => {
                                const line = order?.items.find(
                                  (candidate) => candidate.id === item.purchase_order_item_id,
                                );
                                return (
                                  <li
                                    key={item.id}
                                    className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-xs"
                                  >
                                    <span>
                                      Línea #{item.purchase_order_item_id}
                                      {line === undefined ? null : (
                                        <span className="ml-2 text-ink-500">
                                          {formatMoney(line.unit_price)} / und. ·{" "}
                                          imp. {line.tax_rate}%
                                        </span>
                                      )}
                                    </span>
                                    <span className="font-semibold tabular-nums">
                                      {item.quantity} und.
                                    </span>
                                  </li>
                                );
                              })}
                            </ul>
                          </td>
                        </tr>
                      ) : null}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>

          <footer className="flex items-center justify-between gap-4 border-t border-concrete-200 px-4 py-3 text-sm">
            <p className="text-xs text-ink-500">
              Página {page + 1} de{" "}
              {Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))}
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={page === 0}
                onClick={() => setPage((current) => Math.max(0, current - 1))}
                className="border border-concrete-200 px-3 py-1.5 text-xs font-semibold text-ink-700 hover:border-ink-950 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Anterior
              </button>
              <button
                type="button"
                disabled={(page + 1) * PAGE_SIZE >= filtered.length}
                onClick={() => setPage((current) => current + 1)}
                className="border border-concrete-200 px-3 py-1.5 text-xs font-semibold text-ink-700 hover:border-ink-950 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Siguiente
              </button>
            </div>
          </footer>
        </div>
      )}

      <p className="mt-4 text-xs text-ink-500">
        Para registrar una entrada usa una OC en APPROVED o PARTIALLY_RECEIVED.
        Fecha sugerida: {todayIso()}. Las recepciones no se editan; las
        correcciones se hacen con movimientos de inventario.
      </p>

      <Link
        to="/purchasing/orders"
        className="mt-3 inline-block text-xs font-semibold text-ink-500 underline-offset-2 hover:text-ink-950 hover:underline"
      >
        ← Volver a órdenes de compra
      </Link>

      <GoodsReceiptForm
        open={formOpen}
        order={null}
        onClose={() => setFormOpen(false)}
        onDone={handleDone}
      />
    </div>
  );
}
