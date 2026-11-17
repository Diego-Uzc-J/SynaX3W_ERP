import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { useCustomers, useInvoices } from "../../api/sales";
import type { InvoiceFilters, InvoiceStatus } from "../../api/sales";
import { INVOICE_STATUSES } from "../../api/sales";
import {
  INVOICE_STATUS_HINTS,
  INVOICE_STATUS_LABELS,
} from "./constants";
import { formatDate, formatMoney, todayIso } from "./format";
import SalesTabs from "./SalesTabs";
import { InvoiceStatusBadge } from "./SalesStatusBadge";

const PAGE_SIZE = 15;

type StatusFilter = InvoiceStatus | "all";

export default function InvoiceList() {
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [search, setSearch] = useState("");
  const [customerFilter, setCustomerFilter] = useState("all");
  const [page, setPage] = useState(0);

  const deferredSearch = useDeferredValue(search.trim());

  const filters: InvoiceFilters = {
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

  const invoicesQuery = useInvoices(filters);
  const customersQuery = useCustomers({ limit: 200 });

  useEffect(() => {
    setPage(0);
  }, [deferredSearch, statusFilter, customerFilter]);

  const invoices = invoicesQuery.data ?? [];
  const customers = customersQuery.data ?? [];

  const customerById = useMemo(
    () => new Map(customers.map((customer) => [customer.id, customer])),
    [customers],
  );

  const today = todayIso();
  const pageTotalCents = invoices.reduce(
    (total, invoice) => total + Math.round(Number(invoice.total) * 100),
    0,
  );
  const pendingCents = invoices.reduce(
    (total, invoice) => total + Math.round(Number(invoice.balance_due) * 100),
    0,
  );
  const overdue = invoices.filter(
    (invoice) => invoice.status === "ISSUED" && invoice.due_date < today,
  ).length;

  const hasFilters =
    deferredSearch !== "" ||
    statusFilter !== "all" ||
    customerFilter !== "all";

  function resetFilters() {
    setSearch("");
    setStatusFilter("all");
    setCustomerFilter("all");
  }

  return (
    <div className="mx-auto w-full max-w-[1440px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
      <header className="flex flex-col gap-6 border-b-2 border-ink-950 pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-signal-600">
            Cartera por cobrar
          </p>
          <h1 className="mt-2 text-4xl font-extrabold tracking-tight sm:text-5xl">
            Facturas
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-ink-700">
            Facturas emitidas, pagadas y anuladas. El saldo pendiente se reduce
            con abonos y notas crédito; las facturas emitidas son inmutables.
          </p>
        </div>
        <Link
          to="/sales/orders"
          className="inline-flex shrink-0 items-center justify-center gap-2 border border-ink-950 px-4 py-2.5 text-sm font-semibold text-ink-950 transition-colors hover:bg-ink-950 hover:text-concrete-50"
        >
          Ir a pedidos
          <span aria-hidden="true">→</span>
        </Link>
      </header>

      <SalesTabs />

      <dl className="mt-6 grid grid-cols-2 divide-x divide-concrete-200 border border-concrete-200 bg-white sm:grid-cols-3">
        <div className="px-4 py-3">
          <dt className="text-xs font-semibold text-ink-500">En esta página</dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums">
            {invoices.length}
          </dd>
        </div>
        <div className="px-4 py-3">
          <dt className="text-xs font-semibold text-ink-500">
            Total facturado
          </dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums">
            {formatMoney(pageTotalCents / 100)}
          </dd>
        </div>
        <div className="col-span-2 border-t border-concrete-200 px-4 py-3 sm:col-span-1 sm:border-t-0">
          <dt className="text-xs font-semibold text-ink-500">
            Saldo pendiente
          </dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums">
            {formatMoney(pendingCents / 100)}
          </dd>
          <dd className="mt-0.5 text-xs text-ink-500">
            {overdue === 0
              ? "Sin facturas vencidas en la página"
              : `${overdue} vencida${overdue === 1 ? "" : "s"} en la página`}
          </dd>
        </div>
      </dl>

      <div className="flex flex-col gap-3 py-5">
        <div
          role="group"
          aria-label="Filtrar facturas por estado"
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
            Todas
          </button>
          {INVOICE_STATUSES.map((status) => (
            <button
              key={status}
              type="button"
              aria-pressed={statusFilter === status}
              title={INVOICE_STATUS_HINTS[status]}
              onClick={() => setStatusFilter(status)}
              className={[
                "border px-3 py-1.5 text-xs font-semibold transition-colors",
                statusFilter === status
                  ? "border-ink-950 bg-ink-950 text-concrete-50"
                  : "border-concrete-200 bg-white text-ink-700 hover:border-ink-950",
              ].join(" ")}
            >
              {INVOICE_STATUS_LABELS[status]}
            </button>
          ))}
        </div>

        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-1 flex-col gap-2 sm:flex-row">
            <div className="flex flex-1 border border-concrete-200 bg-white focus-within:border-ink-950">
              <label className="sr-only" htmlFor="invoice-search">
                Buscar facturas por código
              </label>
              <input
                id="invoice-search"
                type="search"
                value={search}
                onChange={(event) => setSearch(event.currentTarget.value)}
                placeholder="Buscar por código (FAC-2026-…)"
                className="min-w-0 flex-1 px-3 py-2 text-sm placeholder:text-concrete-400 focus:outline-none"
              />
            </div>

            <label className="sr-only" htmlFor="invoice-customer-filter">
              Filtrar por cliente
            </label>
            <select
              id="invoice-customer-filter"
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
            {invoices.length} factura{invoices.length === 1 ? "" : "s"} en esta
            página
            {invoicesQuery.isFetching ? " · actualizando" : ""}
          </p>
        </div>
      </div>

      {invoicesQuery.error !== null ? (
        <div className="border border-signal-500/40 bg-signal-100 px-5 py-6">
          <p className="text-sm font-semibold text-signal-600">
            No se pudo cargar la lista de facturas.
          </p>
          <p className="mt-1 text-sm text-ink-700">
            {invoicesQuery.error.message}
          </p>
          <button
            type="button"
            onClick={() => void invoicesQuery.refetch()}
            className="mt-4 border border-signal-500 px-3 py-1.5 text-sm font-semibold text-signal-600 hover:bg-signal-500 hover:text-white"
          >
            Reintentar
          </button>
        </div>
      ) : invoicesQuery.isPending ? (
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
      ) : invoices.length === 0 ? (
        <div className="border border-dashed border-concrete-200 bg-white px-6 py-16 text-center">
          <p className="text-lg font-semibold">
            {hasFilters
              ? "No hay facturas que coincidan con los filtros."
              : "Todavía no hay facturas emitidas."}
          </p>
          <p className="mx-auto mt-2 max-w-sm text-sm text-ink-500">
            {hasFilters
              ? "Cambia el estado, el cliente o el código para ver otras facturas."
              : "Confirma un pedido y emite su factura desde la vista de pedidos."}
          </p>
          {hasFilters ? (
            <button
              type="button"
              onClick={resetFilters}
              className="mt-5 border border-ink-950 px-4 py-2 text-sm font-semibold hover:bg-ink-950 hover:text-concrete-50"
            >
              Limpiar filtros
            </button>
          ) : (
            <Link
              to="/sales/orders"
              className="mt-5 inline-block border border-ink-950 px-4 py-2 text-sm font-semibold hover:bg-ink-950 hover:text-concrete-50"
            >
              Ir a pedidos
            </Link>
          )}
        </div>
      ) : (
        <div className="border border-concrete-200 bg-white">
          <div className="relative overflow-x-auto">
            <table className="w-full min-w-[1040px] border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-concrete-200 text-xs font-semibold text-ink-500">
                  <th scope="col" className="px-4 py-3">
                    Factura
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Cliente
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Emisión
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Vencimiento
                  </th>
                  <th scope="col" className="px-4 py-3 text-right">
                    Total
                  </th>
                  <th scope="col" className="px-4 py-3 text-right">
                    Saldo pendiente
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
                {invoices.map((invoice) => {
                  const customer = customerById.get(invoice.customer_id);
                  const isOverdue =
                    invoice.status === "ISSUED" && invoice.due_date < today;
                  return (
                    <tr
                      key={invoice.id}
                      className="border-b border-concrete-100 hover:bg-concrete-50"
                    >
                      <td className="border-l-2 border-transparent px-4 py-3">
                        <Link
                          to={`/sales/invoices/${invoice.id}`}
                          className="font-semibold tabular-nums text-ink-950 underline-offset-2 hover:underline"
                        >
                          {invoice.code}
                        </Link>
                        <span className="mt-0.5 block text-xs text-ink-500">
                          {invoice.sales_order_id === null
                            ? "Venta directa"
                            : `Pedido #${invoice.sales_order_id}`}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className="block max-w-[220px] truncate font-medium text-ink-950">
                          {customer?.company_name ??
                            `Cliente #${invoice.customer_id}`}
                        </span>
                        <span className="mt-0.5 block text-xs tabular-nums text-ink-500">
                          {customer?.tax_id ?? "—"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-ink-700">
                        {formatDate(invoice.issue_date)}
                      </td>
                      <td className="px-4 py-3 text-xs">
                        <span
                          className={
                            isOverdue
                              ? "font-semibold text-clay-600"
                              : "text-ink-700"
                          }
                        >
                          {formatDate(invoice.due_date)}
                        </span>
                        {isOverdue ? (
                          <span className="mt-0.5 block text-[0.6875rem] font-semibold uppercase tracking-wide text-clay-600">
                            Vencida
                          </span>
                        ) : null}
                      </td>
                      <td className="px-4 py-3 text-right font-semibold tabular-nums">
                        {formatMoney(invoice.total)}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums">
                        <span
                          className={
                            invoice.status === "ISSUED" &&
                            Number(invoice.balance_due) > 0
                              ? "font-semibold text-signal-600"
                              : "text-ink-500"
                          }
                        >
                          {formatMoney(invoice.balance_due)}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <InvoiceStatusBadge status={invoice.status} />
                      </td>
                      <td className="px-4 py-3 text-right">
                        <Link
                          to={`/sales/invoices/${invoice.id}`}
                          className="whitespace-nowrap border border-concrete-200 px-2 py-1 text-[0.6875rem] font-semibold text-ink-700 hover:border-ink-950 hover:text-ink-950"
                        >
                          Ver detalle
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <footer className="flex items-center justify-between gap-4 border-t border-concrete-200 px-4 py-3 text-sm">
            <p className="text-xs text-ink-500">
              Página {page + 1}
              {invoicesQuery.isFetching ? " · actualizando" : ""}
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
                disabled={invoices.length < PAGE_SIZE}
                onClick={() => setPage((current) => current + 1)}
                className="border border-concrete-200 px-3 py-1.5 text-xs font-semibold text-ink-700 hover:border-ink-950 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Siguiente
              </button>
            </div>
          </footer>
        </div>
      )}
    </div>
  );
}
