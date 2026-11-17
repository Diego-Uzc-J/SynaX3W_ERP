import {
  useCallback,
  useDeferredValue,
  useEffect,
  useState,
} from "react";

import { useCustomers } from "../../api/sales";
import type { Customer, CustomerFilters } from "../../api/sales";
import CustomerForm from "./CustomerForm";
import SalesTabs from "./SalesTabs";
import { ActiveBadge } from "./SalesStatusBadge";
import { formatMoney } from "./format";

const PAGE_SIZE = 15;

type SearchField = "company_name" | "tax_id";
type StatusFilter = "all" | "active" | "inactive";

export default function CustomerList() {
  const [searchField, setSearchField] = useState<SearchField>("company_name");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [page, setPage] = useState(0);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Customer | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  const deferredSearch = useDeferredValue(search.trim());

  const filters: CustomerFilters = {
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  };
  if (deferredSearch !== "") {
    if (searchField === "tax_id") {
      filters.tax_id = deferredSearch;
    } else {
      filters.company_name = deferredSearch;
    }
  }
  if (statusFilter !== "all") {
    filters.is_active = statusFilter === "active";
  }

  const customersQuery = useCustomers(filters);

  useEffect(() => {
    setPage(0);
  }, [deferredSearch, searchField, statusFilter]);

  const customers = customersQuery.data ?? [];
  const activeOnPage = customers.filter((customer) => customer.is_active).length;
  const creditOnPageCents = customers.reduce(
    (total, customer) =>
      total + Math.round(Number(customer.credit_limit) * 100),
    0,
  );
  const hasFilters = deferredSearch !== "" || statusFilter !== "all";

  const openCreate = useCallback(() => {
    setEditing(null);
    setFormOpen(true);
  }, []);

  const openEdit = useCallback((customer: Customer) => {
    setEditing(customer);
    setFormOpen(true);
  }, []);

  const closeForm = useCallback(() => setFormOpen(false), []);

  const handleSaved = useCallback(
    (customer: Customer, mode: "created" | "updated") => {
      setFeedback(
        mode === "created"
          ? `Cliente creado: ${customer.company_name} (${customer.tax_id}).`
          : `Cliente actualizado: ${customer.company_name} (${customer.tax_id}).`,
      );
      setFormOpen(false);
      setEditing(null);
    },
    [],
  );

  function resetFilters() {
    setSearch("");
    setSearchField("company_name");
    setStatusFilter("all");
  }

  return (
    <div className="mx-auto w-full max-w-[1440px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
      <header className="flex flex-col gap-6 border-b-2 border-ink-950 pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-signal-600">
            Gestión comercial
          </p>
          <h1 className="mt-2 text-4xl font-extrabold tracking-tight sm:text-5xl">
            Clientes
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-ink-700">
            Cuentas comerciales habilitadas para cotizar, pedir y facturar. El
            cupo de crédito limita la deuda vigente antes de confirmar un
            pedido.
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
          Nuevo cliente
        </button>
      </header>

      <SalesTabs />

      {feedback === null ? null : (
        <div
          role="status"
          className="mt-5 flex items-start justify-between gap-4 border border-pine-600/30 bg-pine-100 px-4 py-3 text-sm font-medium text-pine-600"
        >
          <p>{feedback}</p>
          <button
            type="button"
            onClick={() => setFeedback(null)}
            className="text-base leading-none text-pine-600 hover:text-ink-950"
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
            {customers.length}
          </dd>
        </div>
        <div className="px-4 py-3">
          <dt className="text-xs font-semibold text-ink-500">
            Activos visibles
          </dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums">
            {activeOnPage}
          </dd>
        </div>
        <div className="col-span-2 border-t border-concrete-200 px-4 py-3 sm:col-span-1 sm:border-t-0">
          <dt className="text-xs font-semibold text-ink-500">
            Cupo sumado en la página
          </dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums">
            {formatMoney(creditOnPageCents / 100)}
          </dd>
        </div>
      </dl>

      <div className="flex flex-col gap-3 py-5 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-1 flex-col gap-2 sm:flex-row">
          <div className="flex border border-concrete-200 bg-white focus-within:border-ink-950">
            <label className="sr-only" htmlFor="customer-search">
              Buscar clientes
            </label>
            <select
              aria-label="Buscar por campo"
              value={searchField}
              onChange={(event) =>
                setSearchField(event.currentTarget.value as SearchField)
              }
              className="border-r border-concrete-200 bg-transparent px-2 py-2 text-xs font-semibold text-ink-700"
            >
              <option value="company_name">Razón social</option>
              <option value="tax_id">NIT / ID fiscal</option>
            </select>
            <input
              id="customer-search"
              type="search"
              value={search}
              onChange={(event) => setSearch(event.currentTarget.value)}
              placeholder={
                searchField === "tax_id"
                  ? "Buscar por NIT o identificador"
                  : "Buscar por razón social"
              }
              className="min-w-0 flex-1 px-3 py-2 text-sm placeholder:text-concrete-400 focus:outline-none"
            />
          </div>

          <label className="sr-only" htmlFor="customer-status">
            Filtrar por estado
          </label>
          <select
            id="customer-status"
            value={statusFilter}
            onChange={(event) =>
              setStatusFilter(event.currentTarget.value as StatusFilter)
            }
            className="border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-700"
          >
            <option value="all">Todos los estados</option>
            <option value="active">Solo activos</option>
            <option value="inactive">Solo inactivos</option>
          </select>
        </div>

        <p className="text-xs text-ink-500" aria-live="polite">
          {customers.length} cliente{customers.length === 1 ? "" : "s"} en esta
          página
          {customersQuery.isFetching ? " · actualizando" : ""}
        </p>
      </div>

      {customersQuery.error !== null ? (
        <div className="border border-signal-500/40 bg-signal-100 px-5 py-6">
          <p className="text-sm font-semibold text-signal-600">
            No se pudo cargar la cartera de clientes.
          </p>
          <p className="mt-1 text-sm text-ink-700">
            {customersQuery.error.message}
          </p>
          <button
            type="button"
            onClick={() => void customersQuery.refetch()}
            className="mt-4 border border-signal-500 px-3 py-1.5 text-sm font-semibold text-signal-600 hover:bg-signal-500 hover:text-white"
          >
            Reintentar
          </button>
        </div>
      ) : customersQuery.isPending ? (
        <div className="border border-concrete-200 bg-white">
          {[0, 1, 2, 3, 4].map((row) => (
            <div
              key={row}
              className="flex items-center gap-6 border-b border-concrete-100 px-4 py-4 last:border-b-0"
            >
              <div className="h-4 w-1/3 animate-pulse bg-concrete-100" />
              <div className="h-4 w-1/5 animate-pulse bg-concrete-100" />
              <div className="h-4 w-1/4 animate-pulse bg-concrete-100" />
            </div>
          ))}
        </div>
      ) : customers.length === 0 ? (
        <div className="border border-dashed border-concrete-200 bg-white px-6 py-16 text-center">
          <p className="text-lg font-semibold">
            {hasFilters
              ? "No hay clientes que coincidan con los filtros."
              : "Todavía no hay clientes registrados."}
          </p>
          <p className="mx-auto mt-2 max-w-sm text-sm text-ink-500">
            {hasFilters
              ? "Cambia la búsqueda o el estado para ver otras cuentas."
              : "Registra la primera cuenta comercial para empezar a cotizar y facturar."}
          </p>
          <button
            type="button"
            onClick={hasFilters ? resetFilters : openCreate}
            className="mt-5 border border-ink-950 px-4 py-2 text-sm font-semibold hover:bg-ink-950 hover:text-concrete-50"
          >
            {hasFilters ? "Limpiar filtros" : "Crear el primer cliente"}
          </button>
        </div>
      ) : (
        <div className="border border-concrete-200 bg-white">
          <div className="relative overflow-x-auto">
            <table className="w-full min-w-[920px] border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-concrete-200 text-xs font-semibold text-ink-500">
                  <th scope="col" className="px-4 py-3">
                    Cliente
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Contacto
                  </th>
                  <th scope="col" className="px-4 py-3 text-right">
                    Límite de crédito
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
                {customers.map((customer) => (
                  <tr
                    key={customer.id}
                    className="border-b border-concrete-100 last:border-b-0 hover:bg-concrete-50"
                  >
                    <td className="border-l-2 border-transparent px-4 py-3">
                      <span className="block font-semibold text-ink-950">
                        {customer.company_name}
                      </span>
                      <span className="mt-0.5 block text-xs tabular-nums text-ink-500">
                        {customer.tax_id}
                      </span>
                      <span className="mt-1 block max-w-md truncate text-xs text-concrete-400">
                        {customer.address}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className="block text-ink-700">
                        {customer.contact_name}
                      </span>
                      <span className="mt-0.5 block text-xs text-ink-500">
                        {customer.email}
                      </span>
                      {customer.phone === null ? null : (
                        <span className="mt-0.5 block text-xs tabular-nums text-concrete-400">
                          {customer.phone}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right font-semibold tabular-nums">
                      {formatMoney(customer.credit_limit)}
                    </td>
                    <td className="px-4 py-3">
                      <ActiveBadge isActive={customer.is_active} />
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        type="button"
                        onClick={() => openEdit(customer)}
                        className="border border-concrete-200 px-2.5 py-1.5 text-xs font-semibold text-ink-700 hover:border-ink-950 hover:text-ink-950"
                      >
                        Editar
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <footer className="flex items-center justify-between gap-4 border-t border-concrete-200 px-4 py-3 text-sm">
            <p className="text-xs text-ink-500">
              Página {page + 1}
              {customersQuery.isFetching ? " · actualizando" : ""}
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
                disabled={customers.length < PAGE_SIZE}
                onClick={() => setPage((current) => current + 1)}
                className="border border-concrete-200 px-3 py-1.5 text-xs font-semibold text-ink-700 hover:border-ink-950 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Siguiente
              </button>
            </div>
          </footer>
        </div>
      )}

      <CustomerForm
        open={formOpen}
        customer={editing}
        onClose={closeForm}
        onSaved={handleSaved}
      />
    </div>
  );
}
