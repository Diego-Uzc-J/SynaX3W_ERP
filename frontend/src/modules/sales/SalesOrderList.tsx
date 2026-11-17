import {
  Fragment,
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
} from "react";

import { useProducts } from "../../api/inventory";
import { useCustomers, useSalesOrders } from "../../api/sales";
import type {
  SalesOrder,
  SalesOrderFilters,
  SalesOrderStatus,
} from "../../api/sales";
import { SALES_ORDER_STATUSES } from "../../api/sales";
import {
  ORDER_STATUS_HINTS,
  ORDER_STATUS_LABELS,
  isCancellableOrderStatus,
  isEditableOrderStatus,
  isInvoiceableOrderStatus,
} from "./constants";
import { formatDate, formatMoney } from "./format";
import IssueInvoiceDialog from "./IssueInvoiceDialog";
import { CancelOrderDialog, ConfirmOrderDialog } from "./OrderActionDialogs";
import SalesOrderForm from "./SalesOrderForm";
import SalesTabs from "./SalesTabs";
import { OrderStatusBadge } from "./SalesStatusBadge";

const PAGE_SIZE = 15;

type StatusFilter = SalesOrderStatus | "all";

interface Feedback {
  tone: "success" | "error";
  text: string;
}

const actionClass =
  "border border-concrete-200 px-2 py-1 text-[0.6875rem] font-semibold " +
  "text-ink-700 hover:border-ink-950 hover:text-ink-950";

const primaryActionClass =
  "bg-ink-950 px-2 py-1 text-[0.6875rem] font-semibold text-concrete-50 " +
  "hover:bg-signal-500";

export default function SalesOrderList() {
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [search, setSearch] = useState("");
  const [customerFilter, setCustomerFilter] = useState("all");
  const [page, setPage] = useState(0);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<SalesOrder | null>(null);
  const [confirming, setConfirming] = useState<SalesOrder | null>(null);
  const [cancelling, setCancelling] = useState<SalesOrder | null>(null);
  const [invoicing, setInvoicing] = useState<SalesOrder | null>(null);
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  const deferredSearch = useDeferredValue(search.trim());

  const filters: SalesOrderFilters = {
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  };
  if (statusFilter !== "all") {
    filters.status = statusFilter;
  }
  if (deferredSearch !== "") {
    filters.code = deferredSearch;
  }
  if (customerFilter !== "all") {
    filters.customer_id = Number(customerFilter);
  }

  const ordersQuery = useSalesOrders(filters);
  const customersQuery = useCustomers({ limit: 200 });
  const productsQuery = useProducts({ limit: 200 });

  useEffect(() => {
    setPage(0);
  }, [deferredSearch, statusFilter, customerFilter]);

  const orders = ordersQuery.data ?? [];
  const customers = customersQuery.data ?? [];

  const customerById = useMemo(
    () => new Map(customers.map((customer) => [customer.id, customer])),
    [customers],
  );
  const productById = useMemo(
    () => new Map((productsQuery.data ?? []).map((product) => [product.id, product])),
    [productsQuery.data],
  );

  const pageTotalCents = orders.reduce(
    (total, order) => total + Math.round(Number(order.total) * 100),
    0,
  );
  const confirmedOnPage = orders.filter(
    (order) => order.status === "CONFIRMED",
  ).length;
  const invoicesOnPage = orders.filter((order) =>
    isInvoiceableOrderStatus(order.status),
  ).length;

  const hasFilters =
    deferredSearch !== "" ||
    statusFilter !== "all" ||
    customerFilter !== "all";

  const openCreate = useCallback(() => {
    setEditing(null);
    setFormOpen(true);
  }, []);

  const openEdit = useCallback((order: SalesOrder) => {
    setEditing(order);
    setFormOpen(true);
  }, []);

  const closeForm = useCallback(() => setFormOpen(false), []);

  const handleSaved = useCallback(
    (order: SalesOrder, mode: "created" | "updated") => {
      setFeedback({
        tone: "success",
        text:
          mode === "created"
            ? `Documento ${order.code} creado en estado ${ORDER_STATUS_LABELS[order.status]}.`
            : `Documento ${order.code} actualizado; total ${formatMoney(order.total)}.`,
      });
      setFormOpen(false);
      setEditing(null);
    },
    [],
  );

  const handleActionDone = useCallback((message: string) => {
    setFeedback({ tone: "success", text: message });
    setConfirming(null);
    setCancelling(null);
    setInvoicing(null);
  }, []);

  function resetFilters() {
    setSearch("");
    setStatusFilter("all");
    setCustomerFilter("all");
  }

  const confirmingCustomer =
    confirming === null
      ? null
      : (customerById.get(confirming.customer_id) ?? null);

  return (
    <div className="mx-auto w-full max-w-[1440px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
      <header className="flex flex-col gap-6 border-b-2 border-ink-950 pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-signal-600">
            Ciclo comercial
          </p>
          <h1 className="mt-2 text-4xl font-extrabold tracking-tight sm:text-5xl">
            Pedidos y cotizaciones
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-ink-700">
            Del borrador a la factura. Confirmar valida cupo y descuenta stock;
            cancelar un pedido confirmado revierte el despacho.
          </p>
        </div>
        <button
          type="button"
          onClick={openCreate}
          className="inline-flex shrink-0 items-center justify-center gap-2 bg-signal-500 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-signal-600"
        >
          <span aria-hidden="true" className="text-lg leading-none">
            +
          </span>
          Nuevo pedido
        </button>
      </header>

      <SalesTabs />

      {feedback === null ? null : (
        <div
          role={feedback.tone === "error" ? "alert" : "status"}
          className={[
            "mt-5 flex items-start justify-between gap-4 border px-4 py-3 text-sm font-medium",
            feedback.tone === "success"
              ? "border-pine-600/30 bg-pine-100 text-pine-600"
              : "border-signal-500/40 bg-signal-100 text-signal-600",
          ].join(" ")}
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
          <dt className="text-xs font-semibold text-ink-500">En esta página</dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums">
            {orders.length}
          </dd>
        </div>
        <div className="px-4 py-3">
          <dt className="text-xs font-semibold text-ink-500">
            Importe en la página
          </dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums">
            {formatMoney(pageTotalCents / 100)}
          </dd>
        </div>
        <div className="col-span-2 border-t border-concrete-200 px-4 py-3 sm:col-span-1 sm:border-t-0">
          <dt className="text-xs font-semibold text-ink-500">
            Confirmados / facturables
          </dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums">
            {confirmedOnPage} / {invoicesOnPage}
          </dd>
        </div>
      </dl>

      <div className="flex flex-col gap-3 py-5">
        <div
          role="group"
          aria-label="Filtrar pedidos por estado"
          className="flex flex-wrap gap-1.5"
        >
          <button
            type="button"
            aria-pressed={statusFilter === "all"}
            onClick={() => setStatusFilter("all")}
            className={[
              "border px-3 py-1.5 text-xs font-semibold transition-colors",
              statusFilter === "all"
                ? "border-ink-950 bg-ink-950 text-concrete-50"
                : "border-concrete-200 bg-white text-ink-700 hover:border-ink-950",
            ].join(" ")}
          >
            Todos
          </button>
          {SALES_ORDER_STATUSES.map((status) => (
            <button
              key={status}
              type="button"
              aria-pressed={statusFilter === status}
              title={ORDER_STATUS_HINTS[status]}
              onClick={() => setStatusFilter(status)}
              className={[
                "border px-3 py-1.5 text-xs font-semibold transition-colors",
                statusFilter === status
                  ? "border-ink-950 bg-ink-950 text-concrete-50"
                  : "border-concrete-200 bg-white text-ink-700 hover:border-ink-950",
              ].join(" ")}
            >
              {ORDER_STATUS_LABELS[status]}
            </button>
          ))}
        </div>

        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-1 flex-col gap-2 sm:flex-row">
            <div className="flex flex-1 border border-concrete-200 bg-white focus-within:border-ink-950">
              <label className="sr-only" htmlFor="order-search">
                Buscar pedidos por código
              </label>
              <input
                id="order-search"
                type="search"
                value={search}
                onChange={(event) => setSearch(event.currentTarget.value)}
                placeholder="Buscar por código (PED-2026-…)"
                className="min-w-0 flex-1 px-3 py-2 text-sm placeholder:text-concrete-400 focus:outline-none"
              />
            </div>

            <label className="sr-only" htmlFor="order-customer-filter">
              Filtrar por cliente
            </label>
            <select
              id="order-customer-filter"
              value={customerFilter}
              onChange={(event) => setCustomerFilter(event.currentTarget.value)}
              className="max-w-full border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-700 sm:max-w-xs"
            >
              <option value="all">Todos los clientes</option>
              {customers.map((customer) => (
                <option key={customer.id} value={customer.id}>
                  {customer.company_name}
                </option>
              ))}
            </select>
          </div>

          <p className="text-xs text-ink-500" aria-live="polite">
            {orders.length} documento{orders.length === 1 ? "" : "s"} en esta
            página
            {ordersQuery.isFetching ? " · actualizando" : ""}
          </p>
        </div>
      </div>

      {ordersQuery.error !== null ? (
        <div className="border border-signal-500/40 bg-signal-100 px-5 py-6">
          <p className="text-sm font-semibold text-signal-600">
            No se pudo cargar la lista de pedidos.
          </p>
          <p className="mt-1 text-sm text-ink-700">
            {ordersQuery.error.message}
          </p>
          <button
            type="button"
            onClick={() => void ordersQuery.refetch()}
            className="mt-4 border border-signal-500 px-3 py-1.5 text-sm font-semibold text-signal-600 hover:bg-signal-500 hover:text-white"
          >
            Reintentar
          </button>
        </div>
      ) : ordersQuery.isPending ? (
        <div className="border border-concrete-200 bg-white">
          {[0, 1, 2, 3, 4].map((row) => (
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
      ) : orders.length === 0 ? (
        <div className="border border-dashed border-concrete-200 bg-white px-6 py-16 text-center">
          <p className="text-lg font-semibold">
            {hasFilters
              ? "No hay documentos que coincidan con los filtros."
              : "Todavía no hay pedidos ni cotizaciones."}
          </p>
          <p className="mx-auto mt-2 max-w-sm text-sm text-ink-500">
            {hasFilters
              ? "Cambia el estado, el cliente o el código para ver otros documentos."
              : "Crea la primera cotización para iniciar el ciclo comercial."}
          </p>
          <button
            type="button"
            onClick={hasFilters ? resetFilters : openCreate}
            className="mt-5 border border-ink-950 px-4 py-2 text-sm font-semibold hover:bg-ink-950 hover:text-concrete-50"
          >
            {hasFilters ? "Limpiar filtros" : "Crear el primer pedido"}
          </button>
        </div>
      ) : (
        <div className="border border-concrete-200 bg-white">
          <div className="relative overflow-x-auto">
            <table className="w-full min-w-[1040px] border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-concrete-200 text-xs font-semibold text-ink-500">
                  <th scope="col" className="px-4 py-3">
                    Documento
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Cliente
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Emisión
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Vigencia
                  </th>
                  <th scope="col" className="px-4 py-3 text-right">
                    Total
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Estado
                  </th>
                  <th scope="col" className="px-4 py-3 text-right">
                    <span className="sr-only">Acciones</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {orders.map((order) => {
                  const customer = customerById.get(order.customer_id);
                  const isExpanded = expandedId === order.id;
                  return (
                    <Fragment key={order.id}>
                      <tr
                        key={order.id}
                        className="border-b border-concrete-100 hover:bg-concrete-50"
                      >
                        <td className="border-l-2 border-transparent px-4 py-3">
                          <button
                            type="button"
                            onClick={() =>
                              setExpandedId(isExpanded ? null : order.id)
                            }
                            aria-expanded={isExpanded}
                            className="font-semibold tabular-nums text-ink-950 underline-offset-2 hover:underline"
                          >
                            {order.code}
                          </button>
                          <span className="mt-0.5 block text-xs text-ink-500">
                            {order.items.length} línea
                            {order.items.length === 1 ? "" : "s"} ·{" "}
                            {isExpanded ? "ocultar detalle" : "ver detalle"}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span className="block max-w-[220px] truncate font-medium text-ink-950">
                            {customer?.company_name ??
                              `Cliente #${order.customer_id}`}
                          </span>
                          <span className="mt-0.5 block text-xs tabular-nums text-ink-500">
                            {customer?.tax_id ?? "—"}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-xs text-ink-700">
                          {formatDate(order.issue_date)}
                        </td>
                        <td className="px-4 py-3 text-xs text-ink-700">
                          {order.valid_until === null
                            ? "—"
                            : formatDate(order.valid_until)}
                        </td>
                        <td className="px-4 py-3 text-right font-semibold tabular-nums">
                          {formatMoney(order.total)}
                        </td>
                        <td className="px-4 py-3">
                          <OrderStatusBadge status={order.status} />
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex flex-wrap justify-end gap-1">
                            {isEditableOrderStatus(order.status) ? (
                              <>
                                <button
                                  type="button"
                                  onClick={() => openEdit(order)}
                                  className={actionClass}
                                >
                                  Editar
                                </button>
                                <button
                                  type="button"
                                  onClick={() => setConfirming(order)}
                                  className={primaryActionClass}
                                >
                                  Confirmar
                                </button>
                              </>
                            ) : null}
                            {isInvoiceableOrderStatus(order.status) ? (
                              <button
                                type="button"
                                onClick={() => setInvoicing(order)}
                                className={primaryActionClass}
                              >
                                Facturar
                              </button>
                            ) : null}
                            {isCancellableOrderStatus(order.status) ? (
                              <button
                                type="button"
                                onClick={() => setCancelling(order)}
                                className={actionClass}
                              >
                                Cancelar
                              </button>
                            ) : null}
                            {!isEditableOrderStatus(order.status) &&
                            !isInvoiceableOrderStatus(order.status) &&
                            !isCancellableOrderStatus(order.status) ? (
                              <span className="text-xs text-concrete-400">
                                Sin acciones
                              </span>
                            ) : null}
                          </div>
                        </td>
                      </tr>
                      {isExpanded ? (
                        <tr
                          key={`${order.id}-detail`}
                          className="border-b border-concrete-100 bg-concrete-50"
                        >
                          <td colSpan={7} className="px-4 py-3">
                            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-ink-500">
                              Detalle de líneas
                            </p>
                            <ul className="mt-2 divide-y divide-concrete-200 border border-concrete-200 bg-white">
                              {order.items.map((item) => {
                                const product = productById.get(item.product_id);
                                return (
                                  <li
                                    key={item.id}
                                    className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-xs"
                                  >
                                    <span className="min-w-0">
                                      <span className="block truncate font-medium text-ink-950">
                                        {product === undefined
                                          ? `Producto #${item.product_id}`
                                          : `${product.sku} — ${product.name}`}
                                      </span>
                                      <span className="text-ink-500">
                                        {item.quantity} ×{" "}
                                        {formatMoney(item.unit_price)} · IVA{" "}
                                        {item.tax_rate}%
                                      </span>
                                    </span>
                                    <span className="font-semibold tabular-nums">
                                      {formatMoney(item.subtotal)}
                                    </span>
                                  </li>
                                );
                              })}
                            </ul>
                            <div className="mt-2 flex flex-wrap justify-end gap-x-6 gap-y-1 text-xs">
                              <span className="text-ink-500">
                                Subtotal{" "}
                                <strong className="tabular-nums text-ink-950">
                                  {formatMoney(order.subtotal)}
                                </strong>
                              </span>
                              <span className="text-ink-500">
                                IVA{" "}
                                <strong className="tabular-nums text-ink-950">
                                  {formatMoney(order.tax_amount)}
                                </strong>
                              </span>
                              <span className="text-ink-500">
                                Total{" "}
                                <strong className="tabular-nums text-ink-950">
                                  {formatMoney(order.total)}
                                </strong>
                              </span>
                            </div>
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
              Página {page + 1}
              {ordersQuery.isFetching ? " · actualizando" : ""}
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
                disabled={orders.length < PAGE_SIZE}
                onClick={() => setPage((current) => current + 1)}
                className="border border-concrete-200 px-3 py-1.5 text-xs font-semibold text-ink-700 hover:border-ink-950 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Siguiente
              </button>
            </div>
          </footer>
        </div>
      )}

      <SalesOrderForm
        open={formOpen}
        order={editing}
        onClose={closeForm}
        onSaved={handleSaved}
      />

      <ConfirmOrderDialog
        open={confirming !== null}
        order={confirming}
        customer={confirmingCustomer}
        onClose={() => setConfirming(null)}
        onDone={handleActionDone}
      />

      <CancelOrderDialog
        open={cancelling !== null}
        order={cancelling}
        onClose={() => setCancelling(null)}
        onDone={handleActionDone}
      />

      <IssueInvoiceDialog
        open={invoicing !== null}
        order={invoicing}
        onClose={() => setInvoicing(null)}
        onDone={handleActionDone}
      />
    </div>
  );
}
