import { useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";

import { useProducts } from "../../api/inventory";
import {
  useCreatePurchaseOrder,
  useSuppliers,
  useUpdatePurchaseOrder,
} from "../../api/purchasing";
import type {
  PurchaseOrder,
  PurchaseOrderCreate,
  PurchaseOrderItem,
  PurchaseOrderItemInput,
  PurchaseOrderUpdate,
} from "../../api/purchasing";
import FormSheet from "../../components/FormSheet";
import { DEFAULT_TAX_RATE } from "./constants";
import { errorHint, errorMessage } from "./errors";
import {
  computeLine,
  formatCents,
  formatMoney,
  moneyString,
  parseAmount,
  parseQuantity,
  parseTaxRate,
  todayIso,
  todayPlusDays,
} from "./format";

interface PurchaseOrderFormProps {
  open: boolean;
  /** `null` para crear; una OC en `DRAFT` para actualizar. */
  order: PurchaseOrder | null;
  onClose: () => void;
  onSaved: (order: PurchaseOrder, mode: "created" | "updated") => void;
}

interface LineDraft {
  key: string;
  productId: string;
  quantity: string;
  unitPrice: string;
  taxRate: string;
}

interface Totals {
  subtotalCents: number;
  taxCents: number;
  totalCents: number;
}

const MAX_LINES = 50;
const MAX_LINE_CENTS = 99_999_999_999_999;

const EMPTY_TOTALS: Totals = { subtotalCents: 0, taxCents: 0, totalCents: 0 };

const labelClass = "mb-1.5 block text-xs font-semibold text-ink-700";
const fieldClass =
  "w-full border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-950 " +
  "placeholder:text-concrete-400 focus:border-ink-950";
const hintClass = "mt-1 text-xs text-ink-500";

function draftFromItem(item: PurchaseOrderItem, index: number): LineDraft {
  return {
    key: `existing-${item.id}-${index}`,
    productId: String(item.product_id),
    quantity: String(item.quantity),
    unitPrice: item.unit_price,
    taxRate: item.tax_rate,
  };
}

function blankLine(key: string): LineDraft {
  return {
    key,
    productId: "",
    quantity: "1",
    unitPrice: "",
    taxRate: DEFAULT_TAX_RATE,
  };
}

interface ContentProps {
  order: PurchaseOrder | null;
  onClose: () => void;
  onSaved: (order: PurchaseOrder, mode: "created" | "updated") => void;
}

function PurchaseOrderFormContent({ order, onClose, onSaved }: ContentProps) {
  const isEdit = order !== null;

  const [supplierId, setSupplierId] = useState(
    order === null ? "" : String(order.supplier_id),
  );
  const [issueDate, setIssueDate] = useState(order?.issue_date ?? todayIso());
  const [expectedDate, setExpectedDate] = useState(
    order?.expected_delivery_date ?? todayPlusDays(15),
  );
  const [lines, setLines] = useState<LineDraft[]>(() =>
    order === null
      ? [blankLine("line-initial")]
      : order.items.map(draftFromItem),
  );
  const [formError, setFormError] = useState<string | null>(null);

  const keyCounter = useRef(0);
  function nextKey(): string {
    keyCounter.current += 1;
    return `line-new-${keyCounter.current}`;
  }

  // Se consultan todos los proveedores para poder mostrar (bloqueado) el
  // proveedor de una OC antigua que haya sido dado de baja.
  const suppliersQuery = useSuppliers({ limit: 200 });
  const productsQuery = useProducts({ limit: 200 });

  const createMutation = useCreatePurchaseOrder();
  const updateMutation = useUpdatePurchaseOrder();
  const isPending = createMutation.isPending || updateMutation.isPending;

  const suppliers = suppliersQuery.data ?? [];
  const products = productsQuery.data ?? [];

  const supplierById = useMemo(
    () => new Map(suppliers.map((supplier) => [supplier.id, supplier])),
    [suppliers],
  );
  const productById = useMemo(
    () => new Map(products.map((product) => [product.id, product])),
    [products],
  );

  const selectedSupplier =
    supplierId === "" ? null : (supplierById.get(Number(supplierId)) ?? null);
  const supplierInactive = selectedSupplier !== null && !selectedSupplier.is_active;

  const totals = useMemo<Totals>(() => {
    let result = EMPTY_TOTALS;
    for (const line of lines) {
      const quantity = parseQuantity(line.quantity);
      const unitPrice = parseAmount(line.unitPrice);
      const taxRate = parseTaxRate(line.taxRate);
      if (quantity === null || unitPrice === null || taxRate === null) {
        continue;
      }
      const amounts = computeLine(quantity, unitPrice, taxRate);
      result = {
        subtotalCents: result.subtotalCents + amounts.subtotalCents,
        taxCents: result.taxCents + amounts.taxCents,
        totalCents: result.totalCents + amounts.totalCents,
      };
    }
    return result;
  }, [lines]);

  const queryError = suppliersQuery.error ?? productsQuery.error;
  const mutationError = createMutation.error ?? updateMutation.error;
  const serverMessage = errorMessage(mutationError);
  const serverHint = serverMessage === null ? null : errorHint(serverMessage);
  const visibleError = formError ?? serverMessage;

  function updateLine(
    key: string,
    changes: Partial<Omit<LineDraft, "key">>,
  ) {
    setLines((current) =>
      current.map((line) => (line.key === key ? { ...line, ...changes } : line)),
    );
  }

  function handleProductChange(key: string, productId: string) {
    const product =
      productId === "" ? undefined : productById.get(Number(productId));
    updateLine(key, {
      productId,
      ...(product === undefined ? {} : { unitPrice: product.unit_price }),
    });
  }

  function addLine() {
    if (lines.length >= MAX_LINES) {
      return;
    }
    setLines((current) => [...current, blankLine(nextKey())]);
  }

  function removeLine(key: string) {
    setLines((current) =>
      current.length <= 1 ? current : current.filter((line) => line.key !== key),
    );
  }

  function validate(): string | null {
    if (supplierId === "") {
      return "Selecciona el proveedor de la orden.";
    }
    if (selectedSupplier === null) {
      return "El proveedor seleccionado no está disponible en la consulta.";
    }
    if (supplierInactive) {
      return "El proveedor está inactivo; reactívalo antes de guardar la orden.";
    }
    if (issueDate === "") {
      return "Indica la fecha de emisión.";
    }
    if (expectedDate === "") {
      return "Indica la fecha estimada de entrega.";
    }
    if (expectedDate < issueDate) {
      return "La entrega estimada no puede ser anterior a la emisión.";
    }
    if (lines.length === 0) {
      return "Agrega al menos una línea a la orden.";
    }

    for (const [index, line] of lines.entries()) {
      const label = `Línea ${index + 1}`;
      if (line.productId === "") {
        return `${label}: selecciona un producto del catálogo.`;
      }
      const product = productById.get(Number(line.productId));
      if (product === undefined) {
        return `${label}: el producto no está en el catálogo consultado.`;
      }
      if (!product.is_active) {
        return `${label}: el producto está inactivo; el backend rechazará la orden.`;
      }
      const quantity = parseQuantity(line.quantity);
      if (quantity === null) {
        return `${label}: la cantidad debe ser un entero mayor que cero.`;
      }
      const unitPrice = parseAmount(line.unitPrice);
      if (unitPrice === null) {
        return `${label}: usa un costo unitario válido con hasta 2 decimales.`;
      }
      const taxRate = parseTaxRate(line.taxRate);
      if (taxRate === null) {
        return `${label}: el impuesto debe estar entre 0 y 100 con hasta 2 decimales.`;
      }
      const amounts = computeLine(quantity, unitPrice, taxRate);
      if (amounts.totalCents > MAX_LINE_CENTS) {
        return `${label}: el importe excede el máximo permitido por el ERP.`;
      }
    }
    return null;
  }

  function buildItems(): PurchaseOrderItemInput[] | null {
    const items: PurchaseOrderItemInput[] = [];
    for (const line of lines) {
      const quantity = parseQuantity(line.quantity);
      const unitPrice = parseAmount(line.unitPrice);
      const taxRate = parseTaxRate(line.taxRate);
      if (quantity === null || unitPrice === null || taxRate === null) {
        return null;
      }
      items.push({
        product_id: Number(line.productId),
        quantity,
        unit_price: moneyString(unitPrice),
        tax_rate: moneyString(taxRate),
      });
    }
    return items;
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = validate();
    if (message !== null) {
      setFormError(message);
      return;
    }
    setFormError(null);

    const items = buildItems();
    if (items === null) {
      setFormError("Revisa las cantidades, costos e impuestos de las líneas.");
      return;
    }

    if (order === null) {
      const payload: PurchaseOrderCreate = {
        supplier_id: Number(supplierId),
        issue_date: issueDate,
        expected_delivery_date: expectedDate,
        items,
      };
      createMutation.mutate(payload, {
        onSuccess: (created) => onSaved(created, "created"),
      });
      return;
    }

    const payload: PurchaseOrderUpdate = {
      supplier_id: Number(supplierId),
      issue_date: issueDate,
      expected_delivery_date: expectedDate,
      items,
    };
    updateMutation.mutate(
      { orderId: order.id, payload },
      { onSuccess: (updated) => onSaved(updated, "updated") },
    );
  }

  return (
    <FormSheet
      open
      size="lg"
      title={isEdit ? `Editar orden ${order.code}` : "Nueva orden de compra"}
      subtitle={
        isEdit
          ? "Solo las órdenes en DRAFT admiten cambios en proveedor, fechas y líneas."
          : "El código se genera automáticamente al guardar (OC-AAAA-0000)."
      }
      submitLabel={isEdit ? "Guardar cambios" : "Crear orden"}
      pendingLabel="Guardando…"
      isPending={isPending}
      onClose={onClose}
      onSubmit={handleSubmit}
    >
      <div className="grid gap-4 sm:grid-cols-3">
        <div className="sm:col-span-1">
          <label className={labelClass} htmlFor="order-supplier">
            Proveedor <span className="text-signal-600">*</span>
          </label>
          <select
            id="order-supplier"
            className={fieldClass}
            value={supplierId}
            onChange={(event) => setSupplierId(event.currentTarget.value)}
          >
            <option value="">Selecciona un proveedor</option>
            {supplierId !== "" && supplierById.get(Number(supplierId)) === undefined ? (
              <option value={supplierId}>Proveedor #{supplierId}</option>
            ) : null}
            {suppliers.map((supplier) => (
              <option key={supplier.id} value={supplier.id}>
                {supplier.company_name} · {supplier.tax_id}
                {supplier.is_active ? "" : " (inactivo)"}
              </option>
            ))}
          </select>
          {suppliersQuery.isPending ? (
            <p className={hintClass}>Cargando proveedores…</p>
          ) : null}
        </div>
        <div>
          <label className={labelClass} htmlFor="order-issue-date">
            Fecha de emisión <span className="text-signal-600">*</span>
          </label>
          <input
            id="order-issue-date"
            className={fieldClass}
            type="date"
            value={issueDate}
            onChange={(event) => setIssueDate(event.currentTarget.value)}
          />
        </div>
        <div>
          <label className={labelClass} htmlFor="order-expected-date">
            Entrega estimada <span className="text-signal-600">*</span>
          </label>
          <input
            id="order-expected-date"
            className={fieldClass}
            type="date"
            value={expectedDate}
            onChange={(event) => setExpectedDate(event.currentTarget.value)}
          />
        </div>
      </div>

      {selectedSupplier === null ? null : (
        <div className="border border-concrete-200 bg-white px-4 py-3 text-sm">
          <p className="font-semibold text-ink-950">
            {selectedSupplier.company_name}
          </p>
          <p className="mt-1 text-xs text-ink-500">
            Plazo de pago: {selectedSupplier.payment_terms_days} días ·{" "}
            {selectedSupplier.email}
          </p>
          {supplierInactive ? (
            <p className="mt-2 border-l-2 border-signal-500 bg-signal-100 px-2 py-1 text-xs font-medium text-signal-600">
              El proveedor está inactivo; el backend rechazará la orden hasta
              reactivarlo.
            </p>
          ) : null}
        </div>
      )}

      <section aria-labelledby="order-lines-heading">
        <div className="flex items-end justify-between gap-3 border-b border-concrete-200 pb-2">
          <div>
            <h3
              id="order-lines-heading"
              className="text-sm font-bold tracking-tight"
            >
              Líneas de la orden
            </h3>
            <p className={hintClass}>
              Solo se pueden seleccionar productos activos. El servidor
              recalcula subtotales e impuestos.
            </p>
          </div>
          <button
            type="button"
            onClick={addLine}
            disabled={lines.length >= MAX_LINES}
            className="shrink-0 border border-ink-950 px-3 py-1.5 text-xs font-semibold hover:bg-ink-950 hover:text-concrete-50 disabled:cursor-not-allowed disabled:opacity-40"
          >
            + Agregar línea
          </button>
        </div>

        {productsQuery.isPending ? (
          <p className={hintClass}>Cargando catálogo de productos…</p>
        ) : null}
        {productsQuery.error === null ? null : (
          <p className="mt-2 border-l-2 border-signal-500 bg-signal-100 px-3 py-2 text-xs font-medium text-signal-600">
            No se pudo cargar el catálogo: {productsQuery.error.message}
          </p>
        )}

        <div className="mt-3 space-y-3">
          {lines.map((line, index) => {
            const product =
              line.productId === ""
                ? undefined
                : productById.get(Number(line.productId));
            const inactiveProduct = product !== undefined && !product.is_active;
            const quantity = parseQuantity(line.quantity);
            const unitPrice = parseAmount(line.unitPrice);
            const taxRate = parseTaxRate(line.taxRate);
            const amounts =
              quantity === null || unitPrice === null || taxRate === null
                ? null
                : computeLine(quantity, unitPrice, taxRate);

            return (
              <article
                key={line.key}
                className="border border-concrete-200 bg-white p-3"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="text-xs font-semibold uppercase tracking-[0.14em] text-ink-500">
                    Línea {index + 1}
                  </span>
                  <button
                    type="button"
                    onClick={() => removeLine(line.key)}
                    disabled={lines.length <= 1}
                    className="text-xs font-semibold text-signal-600 hover:text-ink-950 disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    Quitar
                  </button>
                </div>

                <div className="mt-2 grid gap-3 sm:grid-cols-12">
                  <div className="sm:col-span-5">
                    <label
                      className={labelClass}
                      htmlFor={`line-product-${line.key}`}
                    >
                      Producto
                    </label>
                    <select
                      id={`line-product-${line.key}`}
                      className={fieldClass}
                      value={line.productId}
                      onChange={(event) =>
                        handleProductChange(
                          line.key,
                          event.currentTarget.value,
                        )
                      }
                    >
                      <option value="">Selecciona un SKU</option>
                      {line.productId !== "" && product === undefined ? (
                        <option value={line.productId}>
                          Producto #{line.productId}
                        </option>
                      ) : null}
                      {products.map((option) => (
                        <option key={option.id} value={option.id}>
                          {option.sku} — {option.name}
                          {option.is_active ? "" : " (inactivo)"}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="sm:col-span-2">
                    <label
                      className={labelClass}
                      htmlFor={`line-quantity-${line.key}`}
                    >
                      Cantidad
                    </label>
                    <input
                      id={`line-quantity-${line.key}`}
                      className={fieldClass}
                      type="text"
                      inputMode="numeric"
                      value={line.quantity}
                      onChange={(event) =>
                        updateLine(line.key, {
                          quantity: event.currentTarget.value,
                        })
                      }
                    />
                  </div>
                  <div className="sm:col-span-2">
                    <label
                      className={labelClass}
                      htmlFor={`line-price-${line.key}`}
                    >
                      Costo unit.
                    </label>
                    <input
                      id={`line-price-${line.key}`}
                      className={fieldClass}
                      type="text"
                      inputMode="decimal"
                      value={line.unitPrice}
                      onChange={(event) =>
                        updateLine(line.key, {
                          unitPrice: event.currentTarget.value,
                        })
                      }
                    />
                  </div>
                  <div className="sm:col-span-1">
                    <label
                      className={labelClass}
                      htmlFor={`line-tax-${line.key}`}
                    >
                      Imp. %
                    </label>
                    <input
                      id={`line-tax-${line.key}`}
                      className={fieldClass}
                      type="text"
                      inputMode="decimal"
                      value={line.taxRate}
                      onChange={(event) =>
                        updateLine(line.key, {
                          taxRate: event.currentTarget.value,
                        })
                      }
                    />
                  </div>
                  <div className="sm:col-span-2">
                    <p className={labelClass}>Importe</p>
                    <p className="text-sm font-semibold tabular-nums">
                      {amounts === null ? "—" : formatCents(amounts.totalCents)}
                    </p>
                    {amounts === null ? null : (
                      <p className="mt-0.5 text-[0.6875rem] text-ink-500">
                        Subtotal {formatCents(amounts.subtotalCents)} + imp.{" "}
                        {formatCents(amounts.taxCents)}
                      </p>
                    )}
                  </div>
                </div>

                {product === undefined ? null : (
                  <p
                    className={[
                      "mt-2 text-xs",
                      inactiveProduct
                        ? "font-medium text-signal-600"
                        : "text-ink-500",
                    ].join(" ")}
                  >
                    {product.sku} · precio de catálogo{" "}
                    {formatMoney(product.unit_price)}
                    {inactiveProduct
                      ? " · producto inactivo: el backend rechazará la orden."
                      : ""}
                  </p>
                )}
              </article>
            );
          })}
        </div>
      </section>

      <section
        aria-label="Resumen de la orden"
        className="border border-ink-950 bg-white px-4 py-3"
      >
        <dl className="space-y-1.5 text-sm">
          <div className="flex items-center justify-between gap-4">
            <dt className="text-ink-500">Subtotal</dt>
            <dd className="font-semibold tabular-nums">
              {formatCents(totals.subtotalCents)}
            </dd>
          </div>
          <div className="flex items-center justify-between gap-4">
            <dt className="text-ink-500">Impuestos</dt>
            <dd className="font-semibold tabular-nums">
              {formatCents(totals.taxCents)}
            </dd>
          </div>
          <div className="flex items-center justify-between gap-4 border-t border-concrete-200 pt-1.5">
            <dt className="font-bold">Total</dt>
            <dd className="text-lg font-extrabold tabular-nums">
              {formatCents(totals.totalCents)}
            </dd>
          </div>
        </dl>
      </section>

      {queryError === null ? null : (
        <p className="border-l-2 border-signal-500 bg-signal-100 px-3 py-2 text-xs font-medium text-signal-600">
          Algunos datos de apoyo no se pudieron cargar: {queryError.message}
        </p>
      )}

      {visibleError === null ? null : (
        <div
          role="alert"
          className="border-l-2 border-signal-500 bg-signal-100 px-3 py-2 text-sm font-medium text-signal-600"
        >
          <p>{visibleError}</p>
          {serverHint === null ? null : (
            <p className="mt-1 font-normal">{serverHint}</p>
          )}
        </div>
      )}
    </FormSheet>
  );
}

/**
 * Se monta solo al abrirse para que las consultas de apoyo no se ejecuten en
 * cada render de la lista de órdenes.
 */
export default function PurchaseOrderForm({
  open,
  order,
  onClose,
  onSaved,
}: PurchaseOrderFormProps) {
  if (!open) {
    return null;
  }
  return (
    <PurchaseOrderFormContent
      order={order}
      onClose={onClose}
      onSaved={onSaved}
    />
  );
}
