import { useCallback, useDeferredValue, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { useProducts, useStock, useWarehouses } from "../../api/inventory";
import type {
  ProductFilters,
  StockLevel,
  StockMovement,
} from "../../api/inventory";
import InventoryTabs from "./InventoryTabs";
import MovementFormModal from "./MovementFormModal";
import StatusBadge from "./StatusBadge";
import { MOVEMENT_LABELS } from "./constants";
import { formatPrice } from "./format";

const PAGE_SIZE = 12;

type SearchField = "sku" | "name";
type StatusFilter = "all" | "active" | "inactive";

function StockMeter({
  quantity,
  max,
  isLow,
}: {
  quantity: number;
  max: number;
  isLow: boolean;
}) {
  const ratio = max > 0 ? Math.min(1, quantity / max) : 0;
  return (
    <div className="flex items-center justify-end gap-2">
      <span
        className={`w-9 text-right tabular-nums ${
          quantity === 0 ? "text-concrete-400" : "text-ink-950"
        }`}
      >
        {quantity}
      </span>
      <span className="h-1 w-10 shrink-0 bg-concrete-100" aria-hidden="true">
        <span
          className={`block h-full ${isLow ? "bg-signal-500" : "bg-pine-600"}`}
          style={{ width: `${Math.round(ratio * 100)}%` }}
        />
      </span>
    </div>
  );
}

function buildStockIndex(stockLevels: readonly StockLevel[]) {
  const byProduct = new Map<number, Map<number, number>>();
  for (const level of stockLevels) {
    let perWarehouse = byProduct.get(level.product_id);
    if (perWarehouse === undefined) {
      perWarehouse = new Map<number, number>();
      byProduct.set(level.product_id, perWarehouse);
    }
    perWarehouse.set(level.warehouse_id, level.quantity);
  }
  return byProduct;
}

function buildWarehouseMax(stockLevels: readonly StockLevel[]) {
  const max = new Map<number, number>();
  for (const level of stockLevels) {
    const current = max.get(level.warehouse_id) ?? 0;
    if (level.quantity > current) {
      max.set(level.warehouse_id, level.quantity);
    }
  }
  return max;
}

export default function InventoryPage() {
  const [searchField, setSearchField] = useState<SearchField>("name");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [page, setPage] = useState(0);
  const [modalOpen, setModalOpen] = useState(false);
  const [modalProductId, setModalProductId] = useState<number | null>(null);
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
  const productOptionsQuery = useProducts({ limit: 200 });
  const warehousesQuery = useWarehouses({ limit: 100 });
  const stockQuery = useStock({ limit: 500 });

  useEffect(() => {
    setPage(0);
  }, [deferredSearch, searchField, statusFilter]);

  const products = productsQuery.data ?? [];
  const productOptions = productOptionsQuery.data ?? [];
  const warehouses = warehousesQuery.data ?? [];
  const stockLevels = stockQuery.data ?? [];

  const stockByProduct = useMemo(
    () => buildStockIndex(stockLevels),
    [stockLevels],
  );
  const warehouseMax = useMemo(
    () => buildWarehouseMax(stockLevels),
    [stockLevels],
  );

  const totalFor = useCallback(
    (productId: number): number => {
      const perWarehouse = stockByProduct.get(productId);
      if (perWarehouse === undefined) {
        return 0;
      }
      let total = 0;
      for (const quantity of perWarehouse.values()) {
        total += quantity;
      }
      return total;
    },
    [stockByProduct],
  );

  const quantityFor = useCallback(
    (productId: number, warehouseId: number): number =>
      stockByProduct.get(productId)?.get(warehouseId) ?? 0,
    [stockByProduct],
  );

  const pageUnits = products.reduce(
    (sum, product) => sum + totalFor(product.id),
    0,
  );
  const lowStockCount = products.filter(
    (product) => totalFor(product.id) < product.minimum_stock,
  ).length;

  const queryError =
    productsQuery.error ?? warehousesQuery.error ?? stockQuery.error;

  const closeModal = useCallback(() => setModalOpen(false), []);

  const openMovementForm = useCallback((productId: number | null) => {
    setModalProductId(productId);
    setModalOpen(true);
  }, []);

  const handleCreated = useCallback((movement: StockMovement) => {
    setFeedback(
      `Movimiento registrado: ${MOVEMENT_LABELS[movement.movement_type]} de ${
        movement.quantity
      } unidades (${movement.reference_document}).`,
    );
    setModalOpen(false);
  }, []);

  const resetFilters = useCallback(() => {
    setSearch("");
    setSearchField("name");
    setStatusFilter("all");
  }, []);

  function retryAll() {
    void productsQuery.refetch();
    void warehousesQuery.refetch();
    void stockQuery.refetch();
  }

  const stats = [
    { label: "Productos en la página", value: String(products.length) },
    { label: "Bodegas activas", value: String(warehouses.length) },
    {
      label: "Unidades en la página",
      value: stockQuery.isPending ? "—" : String(pageUnits),
    },
    {
      label: "Bajo mínimo",
      value: stockQuery.isPending ? "—" : String(lowStockCount),
    },
  ];

  const hasFilters =
    deferredSearch !== "" || statusFilter !== "all";

  return (
    <div className="mx-auto w-full max-w-[1440px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
      <header className="flex flex-col gap-6 border-b-2 border-ink-950 pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-4xl font-extrabold tracking-tight sm:text-5xl">
            Inventario
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-ink-700">
            Existencias por bodega y registro de entradas, salidas,
            transferencias y ajustes. El saldo se actualiza al guardar cada
            movimiento.
          </p>
        </div>
        <button
          type="button"
          onClick={() => openMovementForm(null)}
          className="inline-flex shrink-0 items-center justify-center gap-2 bg-signal-500 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-signal-600"
        >
          <span aria-hidden="true" className="text-lg leading-none">
            +
          </span>
          Registrar movimiento
        </button>
      </header>

      <InventoryTabs />

      <dl className="grid grid-cols-2 gap-px border-b border-concrete-200 bg-concrete-200 sm:grid-cols-4">
        {stats.map((stat) => (
          <div key={stat.label} className="bg-concrete-50 px-4 py-4">
            <dt className="text-xs font-medium text-ink-500">{stat.label}</dt>
            <dd className="mt-1 text-2xl font-semibold tabular-nums">
              {stat.value}
            </dd>
          </div>
        ))}
      </dl>

      {feedback !== null ? (
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
      ) : null}

      <div className="flex flex-col gap-3 py-5 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-1 flex-col gap-2 sm:flex-row">
          <div className="flex border border-concrete-200 bg-white focus-within:border-ink-950">
            <label className="sr-only" htmlFor="inventory-search">
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
              id="inventory-search"
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

          <label className="sr-only" htmlFor="inventory-status">
            Filtrar por estado
          </label>
          <select
            id="inventory-status"
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
          Página {page + 1}
          {productsQuery.isFetching ? " · actualizando" : ""}
        </p>
      </div>

      {queryError !== null ? (
        <div className="border border-signal-500/40 bg-signal-100 px-5 py-6">
          <p className="text-sm font-semibold text-signal-600">
            No se pudo cargar el inventario.
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
              : "Cuando existan productos podrás registrar entradas y salidas desde aquí."}
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
              to="/inventory/products"
              className="mt-5 inline-block border border-ink-950 px-4 py-2 text-sm font-semibold hover:bg-ink-950 hover:text-concrete-50"
            >
              Ir al catálogo de productos
            </Link>
          )}
        </div>
      ) : (
        <div className="border border-concrete-200 bg-white">
          <div className="relative overflow-x-auto">
            <table className="w-full min-w-[780px] border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-concrete-200 text-xs font-semibold text-ink-500">
                  <th scope="col" className="px-4 py-3">
                    Producto
                  </th>
                  <th scope="col" className="px-4 py-3 text-right">
                    Precio base
                  </th>
                  {warehouses.map((warehouse) => (
                    <th
                      key={warehouse.id}
                      scope="col"
                      className="px-3 py-3 text-right"
                      title={warehouse.name}
                    >
                      {warehouse.code}
                    </th>
                  ))}
                  <th scope="col" className="px-4 py-3 text-right">
                    Total
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Estado
                  </th>
                  <th scope="col" className="px-4 py-3">
                    <span className="sr-only">Acciones</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {products.map((product) => {
                  const total = totalFor(product.id);
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
                      </td>
                      <td className="px-4 py-3 text-right tabular-nums text-ink-700">
                        {formatPrice(product.unit_price)}
                      </td>
                      {warehouses.map((warehouse) => (
                        <td key={warehouse.id} className="px-3 py-3">
                          <StockMeter
                            quantity={quantityFor(product.id, warehouse.id)}
                            max={warehouseMax.get(warehouse.id) ?? 0}
                            isLow={isLow}
                          />
                        </td>
                      ))}
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
                          onClick={() => openMovementForm(product.id)}
                          className="border border-concrete-200 px-2.5 py-1.5 text-xs font-semibold text-ink-700 hover:border-ink-950 hover:text-ink-950"
                        >
                          Movimiento
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
              {products.length} producto{products.length === 1 ? "" : "s"} en
              esta página
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

      <MovementFormModal
        open={modalOpen}
        products={productOptions}
        warehouses={warehouses}
        initialProductId={modalProductId}
        onClose={closeModal}
        onCreated={handleCreated}
      />
    </div>
  );
}
