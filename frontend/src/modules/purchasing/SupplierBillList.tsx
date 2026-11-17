import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import {
  SUPPLIER_BILL_STATUSES,
  usePurchaseOrders,
  useSupplierBills,
  useSuppliers,
} from "../../api/purchasing";
import type {
  SupplierBill,
  SupplierBillFilters,
  SupplierBillStatus,
} from "../../api/purchasing";
import { BILL_STATUS_HINTS, BILL_STATUS_LABELS, canPayBill } from "./constants";
import { formatDate, formatMoney, todayIso } from "./format";
import BillPaymentForm from "./BillPaymentForm";
import PurchasingTabs from "./PurchasingTabs";
import { BillStatusBadge } from "./PurchasingStatusBadge";
import SupplierBillForm from "./SupplierBillForm";

const PAGE_SIZE = 15;

type StatusFilter = SupplierBillStatus | "all";

interface Feedback {
  tone: "success" | "error";
  text: string;
}

/** LISTADO DE CUENTAS POR PAGAR — facturas inmutables con historial de abonos. */
export default function SupplierBillList() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [search, setSearch] = useState("");
  const [supplierFilter, setSupplierFilter] = useState("all");
  const [page, setPage] = useState(0);

  const [formOpen, setFormOpen] = useState(false);
  const [initialOrderId, setInitialOrderId] = useState<number | null>(null);
  const [initialReceiptId, setInitialReceiptId] = useState<number | null>(null);
  const [paying, setPaying] = useState<SupplierBill | null>(null);
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  const deferredSearch = useDeferredValue(search.trim());
  const newFlag = searchParams.get("new");
  const receiptParam = searchParams.get("receipt");

  // Permite llegar desde "Facturar" en el historial de recepciones.
  useEffect(() => {
    if (newFlag !== "1" && receiptParam === null) {
      return;
    }
    const parsedReceipt =
      receiptParam === null ? Number.NaN : Number(receiptParam);
    setInitialReceiptId(
      Number.isInteger(parsedReceipt) && parsedReceipt > 0
        ? parsedReceipt
        : null,
    );
    setInitialOrderId(null);
    setFormOpen(true);
  }, [newFlag, receiptParam]);

  useEffect(() => {
    setPage(0);
  }, [deferredSearch, statusFilter, supplierFilter]);

  const filters: SupplierBillFilters = {
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  };
  if (statusFilter !== "all") {
    filters.status = statusFilter;
  }
  if (deferredSearch !== "") {
    filters.code = deferredSearch;
  }
  if (supplierFilter !== "all") {
    filters.supplier_id = Number(supplierFilter);
  }

  const billsQuery = useSupplierBills(filters);
  const suppliersQuery = useSuppliers({ limit: 200 });
  const ordersQuery = usePurchaseOrders({ limit: 200 });

  const bills = billsQuery.data ?? [];
  const supplierById = useMemo(
    () =>
      new Map(
        (suppliersQuery.data ?? []).map((supplier) => [supplier.id, supplier]),
      ),
    [suppliersQuery.data],
  );
  const orderById = useMemo(
    () =>
      new Map(
        (ordersQuery.data ?? []).map((order) => [order.id, order]),
      ),
    [ordersQuery.data],
  );

  const pageTotalCents = bills.reduce(
    (sum, bill) => sum + Math.round(Number(bill.total) * 100),
    0,
  );
  const pendingCents = bills.reduce(
    (sum, bill) => sum + Math.round(Number(bill.balance_due) * 100),
    0,
  );
  const overdue = bills.filter(
    (bill) => canPayBill(bill.status) && bill.due_date < todayIso(),
  ).length;
  const hasFilters =
    deferredSearch !== "" || statusFilter !== "all" || supplierFilter !== "all";

  function resetFilters() {
    setSearch("");
    setStatusFilter("all");
    setSupplierFilter("all");
  }

  function openCreate() {
    setInitialOrderId(null);
    setInitialReceiptId(null);
    setFormOpen(true);
  }

  function closeForm() {
    setFormOpen(false);
    setInitialOrderId(null);
    setInitialReceiptId(null);
    if (newFlag !== null || receiptParam !== null) {
      setSearchParams({}, { replace: true });
    }
  }

  function handleSaved(_bill: SupplierBill, message: string) {
    setFeedback({ tone: "success", text: message });
    closeForm();
  }

  function handlePaymentDone(message: string) {
    setFeedback({ tone: "success", text: message });
    setPaying(null);
  }

  return (
    <div className="mx-auto w-full max-w-[1440px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
      <header className="flex flex-col gap-6 border-b-2 border-ink-950 pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-signal-600">
            Cuentas por pagar
          </p>
          <h1 className="mt-2 text-4xl font-extrabold tracking-tight sm:text-5xl">
            Facturas de proveedores
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-ink-700">
            Facturas vinculadas a órdenes y recepciones. Los importes se validan
            contra lo recibido; los abonos reducen el saldo sin alterar el
            documento original.
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
          Nueva factura
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
          <dt className="text-xs font-semibold text-ink-500">En esta página</dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums">
            {bills.length}
          </dd>
        </div>
        <div className="px-4 py-3">
          <dt className="text-xs font-semibold text-ink-500">Total facturado</dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums">
            {formatMoney(pageTotalCents / 100)}
          </dd>
        </div>
        <div className="col-span-2 border-t border-concrete-200 px-4 py-3 sm:col-span-1 sm:border-t-0">
          <dt className="text-xs font-semibold text-ink-500">Saldo pendiente</dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums text-signal-600">
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
          {SUPPLIER_BILL_STATUSES.map((status) => (
            <button
              key={status}
              type="button"
              aria-pressed={statusFilter === status}
              title={BILL_STATUS_HINTS[status]}
              onClick={() => setStatusFilter(status)}
              className={[
                "border px-3 py-1.5 text-xs font-semibold transition-colors",
                statusFilter === status
                  ? "border-ink-950 bg-ink-950 text-concrete-50"
                  : "border-concrete-200 bg-white text-ink-700 hover:border-ink-950",
              ].join(" ")}
            >
              {BILL_STATUS_LABELS[status]}
            </button>
          ))}
        </div>

        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-1 flex-col gap-2 sm:flex-row">
            <div className="flex flex-1 border border-concrete-200 bg-white focus-within:border-ink-950">
              <label className="sr-only" htmlFor="bill-search">
                Buscar facturas por código
              </label>
              <input
                id="bill-search"
                type="search"
                value={search}
                onChange={(event) => setSearch(event.currentTarget.value)}
                placeholder="Buscar por código (BILL-2026-…)"
                className="min-w-0 flex-1 px-3 py-2 text-sm placeholder:text-concrete-400 focus:outline-none"
              />
            </div>
            <label className="sr-only" htmlFor="bill-supplier-filter">
              Filtrar por proveedor
            </label>
            <select
              id="bill-supplier-filter"
              value={supplierFilter}
              onChange={(event) => setSupplierFilter(event.currentTarget.value)}
              className="max-w-full border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-700 sm:max-w-xs"
            >
              <option value="all">Todos los proveedores</option>
              {(suppliersQuery.data ?? []).map((supplier) => (
                <option key={supplier.id} value={supplier.id}>
                  {supplier.company_name}
                </option>
              ))}
            </select>
          </div>
          <p className="text-xs text-ink-500" aria-live="polite">
            {bills.length} factura{bills.length === 1 ? "" : "s"} en esta página
            {billsQuery.isFetching ? " · actualizando" : ""}
          </p>
        </div>
      </div>

      {billsQuery.error !== null ? (
        <div className="border border-signal-500/40 bg-signal-100 px-5 py-6">
          <p className="text-sm font-semibold text-signal-600">
            No se pudo cargar la lista de facturas.
          </p>
          <p className="mt-1 text-sm text-ink-700">{billsQuery.error.message}</p>
          <button
            type="button"
            onClick={() => void billsQuery.refetch()}
            className="mt-4 border border-signal-500 px-3 py-1.5 text-sm font-semibold text-signal-600 hover:bg-signal-500 hover:text-white"
          >
            Reintentar
          </button>
        </div>
      ) : billsQuery.isPending ? (
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
      ) : bills.length === 0 ? (
        <div className="border border-dashed border-concrete-200 bg-white px-6 py-16 text-center">
          <p className="text-lg font-semibold">
            {hasFilters
              ? "No hay facturas que coincidan con los filtros."
              : "Todavía no hay facturas de proveedor."}
          </p>
          <p className="mx-auto mt-2 max-w-sm text-sm text-ink-500">
            {hasFilters
              ? "Cambia el estado, el proveedor o el código para ver otras facturas."
              : "Registra una recepción y luego emite la factura contra la OC o esa entrega."}
          </p>
          <button
            type="button"
            onClick={hasFilters ? resetFilters : openCreate}
            className="mt-5 border border-ink-950 px-4 py-2 text-sm font-semibold hover:bg-ink-950 hover:text-concrete-50"
          >
            {hasFilters ? "Limpiar filtros" : "Registrar la primera factura"}
          </button>
        </div>
      ) : (
        <div className="border border-concrete-200 bg-white">
          <div className="relative overflow-x-auto">
            <table className="w-full min-w-[1180px] border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-concrete-200 text-xs font-semibold text-ink-500">
                  <th scope="col" className="px-4 py-3">
                    Factura
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Proveedor
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Origen
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Emisión / vencimiento
                  </th>
                  <th scope="col" className="px-4 py-3 text-right">
                    Total
                  </th>
                  <th scope="col" className="px-4 py-3 text-right">
                    Saldo
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
                {bills.map((bill) => {
                  const supplier = supplierById.get(bill.supplier_id);
                  const order =
                    bill.purchase_order_id === null
                      ? undefined
                      : orderById.get(bill.purchase_order_id);
                  const isOverdue =
                    canPayBill(bill.status) && bill.due_date < todayIso();
                  return (
                    <tr
                      key={bill.id}
                      className="border-b border-concrete-100 hover:bg-concrete-50"
                    >
                      <td className="px-4 py-3">
                        <Link
                          to={`/purchasing/bills/${bill.id}`}
                          className="font-semibold tabular-nums text-ink-950 underline-offset-2 hover:underline"
                        >
                          {bill.code}
                        </Link>
                        <span className="mt-0.5 block max-w-[200px] truncate text-xs text-ink-500">
                          N.º {bill.supplier_invoice_number}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className="block max-w-[220px] truncate font-medium text-ink-950">
                          {supplier?.company_name ??
                            `Proveedor #${bill.supplier_id}`}
                        </span>
                        <span className="mt-0.5 block text-xs tabular-nums text-ink-500">
                          {supplier?.tax_id ?? "—"}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-ink-700">
                        <span className="block tabular-nums">
                          {order?.code ??
                            (bill.purchase_order_id === null
                              ? "—"
                              : `OC #${bill.purchase_order_id}`)}
                        </span>
                        <span className="mt-0.5 block text-ink-500">
                          {bill.goods_receipt_id === null
                            ? "Acumulado"
                            : `Recepción #${bill.goods_receipt_id}`}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-ink-700">
                        <span className="block">{formatDate(bill.issue_date)}</span>
                        <span
                          className={[
                            "mt-0.5 block",
                            isOverdue ? "font-semibold text-signal-600" : "text-ink-500",
                          ].join(" ")}
                        >
                          {formatDate(bill.due_date)}
                          {isOverdue ? " · vencida" : ""}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-right font-semibold tabular-nums">
                        {formatMoney(bill.total)}
                      </td>
                      <td className="px-4 py-3 text-right font-semibold tabular-nums">
                        {formatMoney(bill.balance_due)}
                      </td>
                      <td className="px-4 py-3">
                        <BillStatusBadge status={bill.status} />
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap justify-end gap-1">
                          {canPayBill(bill.status) ? (
                            <button
                              type="button"
                              onClick={() => setPaying(bill)}
                              className="bg-ink-950 px-2 py-1 text-[0.6875rem] font-semibold text-concrete-50 hover:bg-signal-500"
                            >
                              Abonar
                            </button>
                          ) : null}
                          <Link
                            to={`/purchasing/bills/${bill.id}`}
                            className="border border-concrete-200 px-2 py-1 text-[0.6875rem] font-semibold text-ink-700 hover:border-ink-950 hover:text-ink-950"
                          >
                            Ver
                          </Link>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <footer className="flex items-center justify-between gap-4 border-t border-concrete-200 px-4 py-3 text-sm">
            <p className="text-xs text-ink-500">Página {page + 1}</p>
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
                disabled={bills.length < PAGE_SIZE}
                onClick={() => setPage((current) => current + 1)}
                className="border border-concrete-200 px-3 py-1.5 text-xs font-semibold text-ink-700 hover:border-ink-950 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Siguiente
              </button>
            </div>
          </footer>
        </div>
      )}

      <SupplierBillForm
        open={formOpen}
        initialOrderId={initialOrderId}
        initialReceiptId={initialReceiptId}
        onClose={closeForm}
        onSaved={handleSaved}
      />
      <BillPaymentForm
        open={paying !== null}
        bill={paying}
        onClose={() => setPaying(null)}
        onDone={handlePaymentDone}
      />
    </div>
  );
}
