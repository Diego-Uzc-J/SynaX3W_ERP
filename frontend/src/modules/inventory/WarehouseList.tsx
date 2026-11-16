import {
  useCallback,
  useDeferredValue,
  useState,
} from "react";

import { useWarehouses } from "../../api/inventory";
import type { Warehouse, WarehouseFilters } from "../../api/inventory";
import InventoryTabs from "./InventoryTabs";
import WarehouseForm from "./WarehouseForm";
import { formatDate } from "./format";

type SearchField = "code" | "name";
type StatusFilter = "all" | "active" | "inactive";

function WarehouseStatus({ isActive }: { isActive: boolean }) {
  if (!isActive) {
    return (
      <span className="inline-flex shrink-0 items-center gap-1.5 bg-concrete-100 px-2 py-1 text-xs font-semibold text-ink-500">
        <span className="size-1.5 bg-concrete-400" aria-hidden="true" />
        Inactiva
      </span>
    );
  }
  return (
    <span className="inline-flex shrink-0 items-center gap-1.5 bg-pine-100 px-2 py-1 text-xs font-semibold text-pine-600">
      <span className="size-1.5 bg-pine-600" aria-hidden="true" />
      Activa
    </span>
  );
}

export default function WarehouseList() {
  const [searchField, setSearchField] = useState<SearchField>("name");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [formOpen, setFormOpen] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);

  const deferredSearch = useDeferredValue(search.trim());

  // `active_only: false` permite mostrar también las bodegas inactivas y su
  // estado; la API, por defecto, devuelve únicamente las activas.
  const filters: WarehouseFilters = { active_only: false, limit: 200 };
  if (deferredSearch !== "") {
    if (searchField === "code") {
      filters.code = deferredSearch;
    } else {
      filters.name = deferredSearch;
    }
  }

  const warehousesQuery = useWarehouses(filters);
  const warehouses = warehousesQuery.data ?? [];

  const visibleWarehouses =
    statusFilter === "all"
      ? warehouses
      : warehouses.filter(
          (warehouse) =>
            warehouse.is_active === (statusFilter === "active"),
        );
  const activeCount = warehouses.filter(
    (warehouse) => warehouse.is_active,
  ).length;

  const hasFilters = deferredSearch !== "" || statusFilter !== "all";

  const closeForm = useCallback(() => setFormOpen(false), []);

  const handleSaved = useCallback((warehouse: Warehouse) => {
    setFeedback(
      `Bodega creada: ${warehouse.code} — ${warehouse.name}.`,
    );
    setFormOpen(false);
  }, []);

  function resetFilters() {
    setSearch("");
    setSearchField("name");
    setStatusFilter("all");
  }

  return (
    <div className="mx-auto w-full max-w-[1440px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
      <header className="flex flex-col gap-6 border-b-2 border-ink-950 pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-signal-600">
            Almacenes
          </p>
          <h1 className="mt-2 text-4xl font-extrabold tracking-tight sm:text-5xl">
            Bodegas
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-ink-700">
            Ubicaciones físicas o lógicas donde se almacena inventario. Solo las
            bodegas activas se ofrecen al registrar movimientos.
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
          Nueva bodega
        </button>
      </header>

      <InventoryTabs />

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

      <div className="flex flex-col gap-3 py-5 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-1 flex-col gap-2 sm:flex-row">
          <div className="flex border border-concrete-200 bg-white focus-within:border-ink-950">
            <label className="sr-only" htmlFor="warehouse-search">
              Buscar bodegas
            </label>
            <select
              aria-label="Buscar por campo"
              value={searchField}
              onChange={(event) =>
                setSearchField(event.currentTarget.value as SearchField)
              }
              className="border-r border-concrete-200 bg-transparent px-2 py-2 text-xs font-semibold text-ink-700"
            >
              <option value="name">Nombre</option>
              <option value="code">Código</option>
            </select>
            <input
              id="warehouse-search"
              type="search"
              value={search}
              onChange={(event) => setSearch(event.currentTarget.value)}
              placeholder={
                searchField === "code"
                  ? "Buscar por código"
                  : "Buscar por nombre de la bodega"
              }
              className="min-w-0 flex-1 px-3 py-2 text-sm placeholder:text-concrete-400 focus:outline-none"
            />
          </div>

          <label className="sr-only" htmlFor="warehouse-status">
            Filtrar por estado
          </label>
          <select
            id="warehouse-status"
            value={statusFilter}
            onChange={(event) =>
              setStatusFilter(event.currentTarget.value as StatusFilter)
            }
            className="border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-700"
          >
            <option value="all">Todas</option>
            <option value="active">Solo activas</option>
            <option value="inactive">Solo inactivas</option>
          </select>
        </div>

        <p className="text-xs text-ink-500" aria-live="polite">
          {visibleWarehouses.length} bodega
          {visibleWarehouses.length === 1 ? "" : "s"} · {activeCount} activa
          {activeCount === 1 ? "" : "s"}
          {warehousesQuery.isFetching ? " · actualizando" : ""}
        </p>
      </div>

      {warehousesQuery.error !== null ? (
        <div className="border border-signal-500/40 bg-signal-100 px-5 py-6">
          <p className="text-sm font-semibold text-signal-600">
            No se pudieron cargar las bodegas.
          </p>
          <p className="mt-1 text-sm text-ink-700">
            {warehousesQuery.error.message}
          </p>
          <button
            type="button"
            onClick={() => void warehousesQuery.refetch()}
            className="mt-4 border border-signal-500 px-3 py-1.5 text-sm font-semibold text-signal-600 hover:bg-signal-500 hover:text-white"
          >
            Reintentar
          </button>
        </div>
      ) : warehousesQuery.isPending ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((card) => (
            <div
              key={card}
              className="border border-concrete-200 bg-white p-4"
            >
              <div className="h-3 w-24 animate-pulse bg-concrete-100" />
              <div className="mt-4 h-5 w-2/3 animate-pulse bg-concrete-100" />
              <div className="mt-2 h-4 w-1/2 animate-pulse bg-concrete-100" />
            </div>
          ))}
        </div>
      ) : visibleWarehouses.length === 0 ? (
        <div className="border border-dashed border-concrete-200 bg-white px-6 py-16 text-center">
          <p className="text-lg font-semibold">
            {hasFilters
              ? "No hay bodegas que coincidan con los filtros."
              : "Todavía no hay bodegas registradas."}
          </p>
          <p className="mx-auto mt-2 max-w-sm text-sm text-ink-500">
            {hasFilters
              ? "Cambia la búsqueda o el estado para ver otras bodegas."
              : "Registra al menos una bodega para poder recibir inventario."}
          </p>
          <button
            type="button"
            onClick={hasFilters ? resetFilters : () => setFormOpen(true)}
            className="mt-5 border border-ink-950 px-4 py-2 text-sm font-semibold hover:bg-ink-950 hover:text-concrete-50"
          >
            {hasFilters ? "Limpiar filtros" : "Registrar la primera bodega"}
          </button>
        </div>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {visibleWarehouses.map((warehouse) => (
              <article
                key={warehouse.id}
                className={`flex flex-col border border-concrete-200 bg-white ${
                  warehouse.is_active ? "" : "opacity-80"
                }`}
              >
                <div
                  className={`flex items-start justify-between gap-3 border-b border-concrete-100 px-4 py-3 ${
                    warehouse.is_active ? "" : "bg-concrete-100/60"
                  }`}
                >
                  <span className="text-xs font-semibold uppercase tracking-[0.18em] text-ink-500">
                    {warehouse.code}
                  </span>
                  <WarehouseStatus isActive={warehouse.is_active} />
                </div>

                <div className="flex-1 px-4 py-4">
                  <h2
                    className={`text-lg font-semibold leading-tight ${
                      warehouse.is_active ? "text-ink-950" : "text-ink-500"
                    }`}
                  >
                    {warehouse.name}
                  </h2>
                  <p className="mt-1.5 text-sm leading-relaxed text-ink-500">
                    {warehouse.address ?? "Sin dirección registrada"}
                  </p>
                </div>

                <div className="flex items-center justify-between gap-3 border-t border-concrete-100 px-4 py-2.5 text-xs text-ink-500">
                  <span>Alta · {formatDate(warehouse.created_at)}</span>
                  <span className="tabular-nums">ID {warehouse.id}</span>
                </div>
              </article>
            ))}
          </div>

          <p className="mt-4 text-xs text-ink-500">
            Se consultan hasta 200 bodegas por vista.
          </p>
        </>
      )}

      <WarehouseForm
        open={formOpen}
        onClose={closeForm}
        onSaved={handleSaved}
      />
    </div>
  );
}
