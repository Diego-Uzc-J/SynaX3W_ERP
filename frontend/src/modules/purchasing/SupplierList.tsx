import {
  useCallback,
  useDeferredValue,
  useEffect,
  useState,
} from "react";

import { useSuppliers } from "../../api/purchasing";
import type { Supplier, SupplierFilters } from "../../api/purchasing";
import PurchasingTabs from "./PurchasingTabs";
import { ActiveBadge } from "./PurchasingStatusBadge";
import SupplierForm from "./SupplierForm";

const PAGE_SIZE = 15;

type SearchField = "tax_id" | "company_name";
type StatusFilter = "all" | "active" | "inactive";

export default function SupplierList() {
  const [searchField, setSearchField] = useState<SearchField>("tax_id");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [page, setPage] = useState(0);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Supplier | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  const deferredSearch = useDeferredValue(search.trim());

  const filters: SupplierFilters = {
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

  const suppliersQuery = useSuppliers(filters);

  useEffect(() => {
    setPage(0);
  }, [deferredSearch, searchField, statusFilter]);

  const suppliers = suppliersQuery.data ?? [];
  const activeOnPage = suppliers.filter((supplier) => supplier.is_active).length;
  const averageTerms =
    suppliers.length === 0
      ? 0
      : Math.round(
          suppliers.reduce(
            (total, supplier) => total + supplier.payment_terms_days,
            0,
          ) / suppliers.length,
        );
  const hasFilters = deferredSearch !== "" || statusFilter !== "all";

  const openCreate = useCallback(() => {
    setEditing(null);
    setFormOpen(true);
  }, []);

  const openEdit = useCallback((supplier: Supplier) => {
    setEditing(supplier);
    setFormOpen(true);
  }, []);

  const closeForm = useCallback(() => setFormOpen(false), []);

  const handleSaved = useCallback(
    (supplier: Supplier, mode: "created" | "updated") => {
      setFeedback(
        mode === "created"
          ? `Proveedor creado: ${supplier.company_name} (${supplier.tax_id}).`
          : `Proveedor actualizado: ${supplier.company_name} (${supplier.tax_id}).`,
      );
      setFormOpen(false);
      setEditing(null);
    },
    [],
  );

  function resetFilters() {
    setSearch("");
    setSearchField("tax_id");
    setStatusFilter("all");
  }

  return (
    <div className="mx-auto w-full max-w-[1440px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
      <header className="flex flex-col gap-6 border-b-2 border-ink-950 pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-signal-600">
            Gestión de aprovisionamiento
          </p>
          <h1 className="mt-2 text-4xl font-extrabold tracking-tight sm:text-5xl">
            Proveedores
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-ink-700">
            Terceros habilitados para recibir órdenes de compra. Solo los
            proveedores activos pueden operar; el NIT identifica cada cuenta de
            forma única.
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
          Nuevo proveedor
        </button>
      </header>

      <PurchasingTabs />

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
            {suppliers.length}
          </dd>
        </div>
        <div className="px-4 py-3">
          <dt className="text-xs font-semibold text-ink-500">Activos visibles</dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums">
            {activeOnPage}
          </dd>
        </div>
        <div className="col-span-2 border-t border-concrete-200 px-4 py-3 sm:col-span-1 sm:border-t-0">
          <dt className="text-xs font-semibold text-ink-500">
            Plazo medio de pago
          </dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums">
            {averageTerms} días
          </dd>
        </div>
      </dl>

      <div className="flex flex-col gap-3 py-5 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-1 flex-col gap-2 sm:flex-row">
          <div className="flex border border-concrete-200 bg-white focus-within:border-ink-950">
            <label className="sr-only" htmlFor="supplier-search">
              Buscar proveedores
            </label>
            <select
              aria-label="Buscar por campo"
              value={searchField}
              onChange={(event) =>
                setSearchField(event.currentTarget.value as SearchField)
              }
              className="border-r border-concrete-200 bg-transparent px-2 py-2 text-xs font-semibold text-ink-700"
            >
              <option value="tax_id">NIT / ID fiscal</option>
              <option value="company_name">Razón social</option>
            </select>
            <input
              id="supplier-search"
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

          <label className="sr-only" htmlFor="supplier-status">
            Filtrar por estado
          </label>
          <select
            id="supplier-status"
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
          {suppliers.length} proveedor{suppliers.length === 1 ? "" : "es"} en
          esta página
          {suppliersQuery.isFetching ? " · actualizando" : ""}
        </p>
      </div>

      {suppliersQuery.error !== null ? (
        <div className="border border-signal-500/40 bg-signal-100 px-5 py-6">
          <p className="text-sm font-semibold text-signal-600">
            No se pudo cargar la lista de proveedores.
          </p>
          <p className="mt-1 text-sm text-ink-700">
            {suppliersQuery.error.message}
          </p>
          <button
            type="button"
            onClick={() => void suppliersQuery.refetch()}
            className="mt-4 border border-signal-500 px-3 py-1.5 text-sm font-semibold text-signal-600 hover:bg-signal-500 hover:text-white"
          >
            Reintentar
          </button>
        </div>
      ) : suppliersQuery.isPending ? (
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
      ) : suppliers.length === 0 ? (
        <div className="border border-dashed border-concrete-200 bg-white px-6 py-16 text-center">
          <p className="text-lg font-semibold">
            {hasFilters
              ? "No hay proveedores que coincidan con los filtros."
              : "Todavía no hay proveedores registrados."}
          </p>
          <p className="mx-auto mt-2 max-w-sm text-sm text-ink-500">
            {hasFilters
              ? "Cambia la búsqueda o el estado para ver otros proveedores."
              : "Registra el primer proveedor para empezar a emitir órdenes de compra."}
          </p>
          <button
            type="button"
            onClick={hasFilters ? resetFilters : openCreate}
            className="mt-5 border border-ink-950 px-4 py-2 text-sm font-semibold hover:bg-ink-950 hover:text-concrete-50"
          >
            {hasFilters ? "Limpiar filtros" : "Crear el primer proveedor"}
          </button>
        </div>
      ) : (
        <div className="border border-concrete-200 bg-white">
          <div className="relative overflow-x-auto">
            <table className="w-full min-w-[980px] border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-concrete-200 text-xs font-semibold text-ink-500">
                  <th scope="col" className="px-4 py-3">
                    Proveedor
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Contacto
                  </th>
                  <th scope="col" className="px-4 py-3 text-right">
                    Plazo de pago
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
                {suppliers.map((supplier) => (
                  <tr
                    key={supplier.id}
                    className="border-b border-concrete-100 last:border-b-0 hover:bg-concrete-50"
                  >
                    <td className="border-l-2 border-transparent px-4 py-3">
                      <span className="block font-semibold text-ink-950">
                        {supplier.company_name}
                      </span>
                      <span className="mt-0.5 block text-xs tabular-nums text-ink-500">
                        {supplier.tax_id}
                      </span>
                      <span className="mt-1 block max-w-md truncate text-xs text-concrete-400">
                        {supplier.address}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span className="block text-ink-700">
                        {supplier.contact_name}
                      </span>
                      <span className="mt-0.5 block text-xs text-ink-500">
                        {supplier.email}
                      </span>
                      {supplier.phone === null ? null : (
                        <span className="mt-0.5 block text-xs tabular-nums text-concrete-400">
                          {supplier.phone}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right font-semibold tabular-nums">
                      {supplier.payment_terms_days} días
                    </td>
                    <td className="px-4 py-3">
                      <ActiveBadge isActive={supplier.is_active} />
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        type="button"
                        onClick={() => openEdit(supplier)}
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
              {suppliersQuery.isFetching ? " · actualizando" : ""}
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
                disabled={suppliers.length < PAGE_SIZE}
                onClick={() => setPage((current) => current + 1)}
                className="border border-concrete-200 px-3 py-1.5 text-xs font-semibold text-ink-700 hover:border-ink-950 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Siguiente
              </button>
            </div>
          </footer>
        </div>
      )}

      <SupplierForm
        open={formOpen}
        supplier={editing}
        onClose={closeForm}
        onSaved={handleSaved}
      />
    </div>
  );
}
