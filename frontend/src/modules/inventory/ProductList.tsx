import {
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
} from "react";

import { useProducts, useStock } from "../../api/inventory";
import type { Product, ProductFilters } from "../../api/inventory";
import InventoryTabs from "./InventoryTabs";
import ProductForm from "./ProductForm";
import StatusBadge from "./StatusBadge";
import { formatPrice } from "./format";

const PAGE_SIZE = 20;

type SearchField = "sku" | "name";
type StatusFilter = "all" | "active" | "inactive";

export default function ProductList() {
  const [searchField, setSearchField] = useState<SearchField>("name");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [page, setPage] = useState(0);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Product | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  const deferredSearch = useDeferredValue(search.trim());

  const filters: ProductFilters = {
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  };
  if (deferredSearch !== "") {
    if (searchField === "sku") {
      filters.sku = deferredSearch;
    } else {
      filters.name = deferredSearch;
    }
  }
  if (statusFilter !== "all") {
    filters.is_active = statusFilter === "active";
  }

  const productsQuery = useProducts(filters);
  const stockQuery = useStock({ limit: 500 });

  useEffect(() => {
    setPage(0);
  }, [deferredSearch, searchField, statusFilter]);

  const products = productsQuery.data ?? [];

  const totalByProduct = useMemo(() => {
    const totals = new Map<number, number>();
    for (const level of stockQuery.data ?? []) {
      totals.set(level.product_id, (totals.get(level.product_id) ?? 0) + level.quantity);
    }
    return totals;
  }, [stockQuery.data]);

  const lowStockCount = products.filter(
    (product) => (totalByProduct.get(product.id) ?? 0) < product.minimum_stock,
  ).length;

  const queryError = productsQuery.error ?? stockQuery.error;
  const hasFilters = deferredSearch !== "" || statusFilter !== "all";

  const openCreate = useCallback(() => {
    setEditing(null);
    setFormOpen(true);
  }, []);

  const openEdit = useCallback((product: Product) => {
    setEditing(product);
    setFormOpen(true);
  }, []);

  const closeForm = useCallback(() => setFormOpen(false), []);

  const handleSaved = useCallback(
    (product: Product, mode: "created" | "updated") => {
      setFeedback(
        mode === "created"
          ? `Producto creado: ${product.sku} — ${product.name}.`
          : `Producto actualizado: ${product.sku} — ${product.name}.`,
      );
      setFormOpen(false);
      setEditing(null);
    },
    [],
  );

  function retryAll() {
    void productsQuery.refetch();
    void stockQuery.refetch();
  }

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
            Catálogo
          </p>
          <h1 className="mt-2 text-4xl font-extrabold tracking-tight sm:text-5xl">
            Productos
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-ink-700">
            Alta y mantenimiento de SKUs. El stock mínimo define cuándo un
            producto aparece como bajo mínimo en las existencias.
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
          Nuevo producto
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
            <label className="sr-only" htmlFor="product-search">
              Buscar productos
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
              <option value="sku">SKU</option>
            </select>
            <input
              id="product-search"
              type="search"
              value={search}
              onChange={(event) => setSearch(event.currentTarget.value)}
              placeholder={
                searchField === "sku"
                  ? "Buscar por SKU"
                  : "Buscar por nombre del producto"
              }
              className="min-w-0 flex-1 px-3 py-2 text-sm placeholder:text-concrete-400 focus:outline-none"
            />
          </div>

          <label className="sr-only" htmlFor="product-status">
            Filtrar por estado
          </label>
          <select
            id="product-status"
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
          {products.length} producto{products.length === 1 ? "" : "s"} en esta
          página
          {lowStockCount === 0 ? "" : ` · ${lowStockCount} bajo mínimo`}
          {productsQuery.isFetching ? " · actualizando" : ""}
        </p>
      </div>

      {queryError !== null ? (
        <div className="border border-signal-500/40 bg-signal-100 px-5 py-6">
          <p className="text-sm font-semibold text-signal-600">
            No se pudo cargar el catálogo.
          </p>
          <p className="mt-1 text-sm text-ink-700">{queryError.message}</p>
          <button
            type="button"
            onClick={retryAll}
            className="mt-4 border border-signal-500 px-3 py-1.5 text-sm font-semibold text-signal-600 hover:bg-signal-500 hover:text-white"
          >
            Reintentar
          </button>
        </div>
      ) : productsQuery.isPending ? (
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
      ) : products.length === 0 ? (
        <div className="border border-dashed border-concrete-200 bg-white px-6 py-16 text-center">
          <p className="text-lg font-semibold">
            {hasFilters
              ? "No hay productos que coincidan con los filtros."
              : "Todavía no hay productos en el catálogo."}
          </p>
          <p className="mx-auto mt-2 max-w-sm text-sm text-ink-500">
            {hasFilters
              ? "Cambia la búsqueda o el estado para ver otros productos."
              : "Crea el primer SKU para empezar a registrar existencias y movimientos."}
          </p>
          <button
            type="button"
            onClick={hasFilters ? resetFilters : openCreate}
            className="mt-5 border border-ink-950 px-4 py-2 text-sm font-semibold hover:bg-ink-950 hover:text-concrete-50"
          >
            {hasFilters ? "Limpiar filtros" : "Crear el primer producto"}
          </button>
        </div>
      ) : (
        <div className="border border-concrete-200 bg-white">
          <div className="relative overflow-x-auto">
            <table className="w-full min-w-[860px] border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-concrete-200 text-xs font-semibold text-ink-500">
                  <th scope="col" className="px-4 py-3">
                    Producto
                  </th>
                  <th scope="col" className="px-4 py-3 text-right">
                    Precio base
                  </th>
                  <th scope="col" className="px-4 py-3 text-right">
                    Stock mínimo
                  </th>
                  <th scope="col" className="px-4 py-3 text-right">
                    Existencias
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
                {products.map((product) => {
                  const total = totalByProduct.get(product.id) ?? 0;
                  const isLow = total < product.minimum_stock;
                  return (
                    <tr
                      key={product.id}
                      className="border-b border-concrete-100 last:border-b-0 hover:bg-concrete-50"
                    >
                      <td
                        className={`px-4 py-3 ${
                          isLow
                            ? "border-l-2 border-signal-500"
                            : "border-l-2 border-transparent"
                        }`}
                      >
                        <span className="block font-semibold text-ink-950">
                          {product.name}
                        </span>
                        <span className="mt-0.5 block text-xs tabular-nums text-ink-500">
                          {product.sku}
                        </span>
                        {product.description === null ? null : (
                          <span className="mt-1 block max-w-md truncate text-xs text-concrete-400">
                            {product.description}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-ink-700">
                        {formatPrice(product.unit_price)}
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-ink-500">
                        {product.minimum_stock}
                      </td>
                      <td className="px-4 py-3 text-right font-semibold tabular-nums">
                        {total}
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge
                          isActive={product.is_active}
                          isLow={isLow}
                        />
                      </td>
                      <td className="px-4 py-3 text-right">
                        <button
                          type="button"
                          onClick={() => openEdit(product)}
                          className="border border-concrete-200 px-2.5 py-1.5 text-xs font-semibold text-ink-700 hover:border-ink-950 hover:text-ink-950"
                        >
                          Editar
                        </button>
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
              {productsQuery.isFetching ? " · actualizando" : ""}
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
                disabled={products.length < PAGE_SIZE}
                onClick={() => setPage((current) => current + 1)}
                className="border border-concrete-200 px-3 py-1.5 text-xs font-semibold text-ink-700 hover:border-ink-950 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Siguiente
              </button>
            </div>
          </footer>
        </div>
      )}

      <ProductForm
        open={formOpen}
        product={editing}
        onClose={closeForm}
        onSaved={handleSaved}
      />
    </div>
  );
}
