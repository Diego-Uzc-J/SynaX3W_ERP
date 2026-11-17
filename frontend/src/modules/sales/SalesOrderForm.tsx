import { useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";

import { useProducts, useStock } from "../../api/inventory";
import {
  useCreateSalesOrder,
  useCustomers,
  useUpdateSalesOrder,
} from "../../api/sales";
import type {
  EditableOrderStatus,
  SalesOrder,
  SalesOrderCreate,
  SalesOrderItem,
  SalesOrderItemInput,
  SalesOrderUpdate,
} from "../../api/sales";
import FormSheet from "../../components/FormSheet";
import { DEFAULT_TAX_RATE, isEditableOrderStatus } from "./constants";
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
} from "./format";

interface SalesOrderFormProps {
  open: boolean;
  /** `null` para crear; un pedido editable para actualizar. */
  order: SalesOrder | null;
  onClose: () => void;
  onSaved: (order: SalesOrder, mode: "created" | "updated") => void;
}

interface LineDraft {
  key: string;
  productId: string;
  quantity: string;
  unitPrice: string;
  taxRate: string;
}

const MAX_LINES = 50;
const MAX_LINE_CENTS = 99_999_999_999_999;

const labelClass = "mb-1.5 block text-xs font-semibold text-ink-700";
const fieldClass =
  "w-full border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-950 " +
  "placeholder:text-concrete-400 focus:border-ink-950";
const hintClass = "mt-1 text-xs text-ink-500";

function draftFromItem(item: SalesOrderItem, index: number): LineDraft {
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

interface Totals {
  subtotalCents: number;
  taxCents: number;
  totalCents: number;
}

const EMPTY_TOTALS: Totals = { subtotalCents: 0, taxCents: 0, totalCents: 0 };

interface ContentProps {
  order: SalesOrder | null;
  onClose: () => void;
  onSaved: (order: SalesOrder, mode: "created" | "updated") => void;
}

function SalesOrderFormContent({ order, onClose, onSaved }: ContentProps) {
  const isEdit = order !== null;

  const [customerId, setCustomerId] = useState(
    order === null ? "" : String(order.customer_id),
  );
  const [status, setStatus] = useState<EditableOrderStatus>(() => {
    if (order !== null && isEditableOrderStatus(order.status)) {
      return order.status === "QUOTATION" ? "QUOTATION" : "DRAFT";
    }
    return "DRAFT";
  });
  const [issueDate, setIssueDate] = useState(order?.issue_date ?? todayIso());
  const [validUntil, setValidUntil] = useState(order?.valid_until ?? "");
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

  const customersQuery = useCustomers({ limit: 200 });
  const productsQuery = useProducts({ limit: 200 });
  const stockQuery = useStock({ limit: 500 });

  const createMutation = useCreateSalesOrder();
  const updateMutation = useUpdateSalesOrder();
  const isPending = createMutation.isPending || updateMutation.isPending;

  const customers = customersQuery.data ?? [];
  const products = productsQuery.data ?? [];

  const customerById = useMemo(
    () => new Map(customers.map((customer) => [customer.id, customer])),
    [customers],
  );
  const productById = useMemo(
    () => new Map(products.map((product) => [product.id, product])),
    [products],
  );
  const stockByProduct = useMemo(() => {
    const totals = new Map<number, number>();
    for (const level of stockQuery.data ?? []) {
      totals.set(
        level.product_id,
        (totals.get(level.product_id) ?? 0) + level.quantity,
      );
    }
    return totals;
  }, [stockQuery.data]);

  const selectedCustomer =
    customerId === "" ? null : (customerById.get(Number(customerId)) ?? null);

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

  const queryError = customersQuery.error ?? productsQuery.error;
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
    if (customerId === "") {
      return "Selecciona el cliente del pedido.";
    }
    if (customerById.get(Number(customerId)) === undefined) {
      return "El cliente seleccionado no está disponible en la cartera consultada.";
    }
    if (issueDate === "") {
      return "Indica la fecha de emisión.";
    }
    if (validUntil !== "" && validUntil < issueDate) {
      return "La vigencia no puede ser anterior a la fecha de emisión.";
    }
    if (lines.length === 0) {
      return "Agrega al menos una línea al pedido.";
    }

    for (const [index, line] of lines.entries()) {
      const label = `Línea ${index + 1}`;
      if (line.productId === "") {
        return `${label}: selecciona un producto.`;
      }
      if (!productById.has(Number(line.productId))) {
        return `${label}: el producto no está en el catálogo consultado.`;
      }
      const quantity = parseQuantity(line.quantity);
      if (quantity === null) {
        return `${label}: la cantidad debe ser un entero mayor que cero.`;
      }
      const unitPrice = parseAmount(line.unitPrice);
      if (unitPrice === null) {
        return `${label}: usa un precio unitario válido con hasta 2 decimales.`;
      }
      const taxRate = parseTaxRate(line.taxRate);
      if (taxRate === null) {
        return `${label}: el IVA debe estar entre 0 y 100 con hasta 2 decimales.`;
      }
      const amounts = computeLine(quantity, unitPrice, taxRate);
      if (amounts.totalCents > MAX_LINE_CENTS) {
        return `${label}: el importe excede el máximo permitido por el ERP.`;
      }
    }
    return null;
  }

  function buildItems(): SalesOrderItemInput[] | null {
    const items: SalesOrderItemInput[] = [];
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
      setFormError("Revisa las cantidades, precios e IVA de las líneas.");
      return;
    }

    const customerIdValue = Number(customerId);
    const validUntilValue = validUntil === "" ? null : validUntil;

    if (order === null) {
      const payload: SalesOrderCreate = {
        customer_id: customerIdValue,
        status,
        issue_date: issueDate,
        valid_until: validUntilValue,
        items,
      };
      createMutation.mutate(payload, {
        onSuccess: (created) => onSaved(created, "created"),
      });
      return;
    }

    const payload: SalesOrderUpdate = {
      customer_id: customerIdValue,
      status,
      issue_date: issueDate,
      valid_until: validUntilValue,
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
      title={isEdit ? `Editar pedido ${order.code}` : "Nuevo pedido o cotización"}
      subtitle={
        isEdit
          ? "Solo los documentos en borrador o cotización admiten cambios en sus líneas."
          : "El código se genera automáticamente al guardar (PED-AAAA-0000)."
      }
      submitLabel={isEdit ? "Guardar cambios" : "Crear documento"}
      pendingLabel="Guardando…"
      isPending={isPending}
      onClose={onClose}
      onSubmit={handleSubmit}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className={labelClass} htmlFor="order-customer">
            Cliente <span className="text-signal-600">*</span>
          </label>
          <select
            id="order-customer"
            className={fieldClass}
            value={customerId}
            onChange={(event) => setCustomerId(event.currentTarget.value)}
          >
            <option value="">Selecciona un cliente</option>
            {customers.map((customer) => (
              <option key={customer.id} value={customer.id}>
                {customer.company_name} · {customer.tax_id}
                {customer.is_active ? "" : " (inactivo)"}
              </option>
            ))}
            {customerId !== "" && !customerById.has(Number(customerId)) ? (
              <option value={customerId}>Cliente #{customerId}</option>
            ) : null}
          </select>
          {customersQuery.isPending ? (
            <p className={hintClass}>Cargando cartera de clientes…</p>
          ) : null}
        </div>

        <div>
          <label className={labelClass} htmlFor="order-status">
            Estado inicial <span className="text-signal-600">*</span>
          </label>
          <select
            id="order-status"
            className={fieldClass}
            value={status}
            onChange={(event) =>
              setStatus(event.currentTarget.value as EditableOrderStatus)
            }
          >
            <option value="DRAFT">Borrador (DRAFT)</option>
            <option value="QUOTATION">Cotización (QUOTATION)</option>
          </select>
          <p className={hintClass}>
            Ambos estados son editables y aún no descuentan inventario.
          </p>
        </div>
      </div>

      {selectedCustomer === null ? null : (
        <div className="border border-concrete-200 bg-white px-4 py-3 text-sm">
          <p className="font-semibold text-ink-950">
            {selectedCustomer.company_name}
          </p>
          <p className="mt-1 text-xs text-ink-500">
            Cupo de crédito: {formatMoney(selectedCustomer.credit_limit)} ·{" "}
            {selectedCustomer.email}
          </p>
          {selectedCustomer.is_active ? null : (
            <p className="mt-2 border-l-2 border-signal-500 bg-signal-100 px-2 py-1 text-xs font-medium text-signal-600">
              El cliente está inactivo; el backend rechazará el pedido hasta
              reactivarlo.
            </p>
          )}
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
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
          <label className={labelClass} htmlFor="order-valid-until">
            Vigencia{" "}
            <span className="font-normal text-ink-500">(opcional)</span>
          </label>
          <input
            id="order-valid-until"
            className={fieldClass}
            type="date"
            value={validUntil}
            onChange={(event) => setValidUntil(event.currentTarget.value)}
          />
        </div>
      </div>

      <section aria-labelledby="order-lines-heading">
        <div className="flex items-end justify-between gap-3 border-b border-concrete-200 pb-2">
          <div>
            <h3
              id="order-lines-heading"
              className="text-sm font-bold tracking-tight"
            >
              Líneas del documento
            </h3>
            <p className={hintClass}>
              Precio e IVA se pueden ajustar; el servidor recalcula los totales.
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
            const available =
              product === undefined
                ? null
                : (stockByProduct.get(product.id) ?? 0);
            const quantity = parseQuantity(line.quantity);
            const stockWarning =
              available !== null &&
              quantity !== null &&
              quantity > available;

            const amounts = (() => {
              const price = parseAmount(line.unitPrice);
              const tax = parseTaxRate(line.taxRate);
              if (quantity === null || price === null || tax === null) {
                return null;
              }
              return computeLine(quantity, price, tax);
            })();

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
                      {line.productId !== "" &&
                      productById.get(Number(line.productId)) === undefined ? (
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
                      Precio unit.
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
                      IVA %
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
                        Subtotal {formatCents(amounts.subtotalCents)} + IVA{" "}
                        {formatCents(amounts.taxCents)}
                      </p>
                    )}
                  </div>
                </div>

                {product === undefined ? null : (
                  <p
                    className={[
                      "mt-2 text-xs",
                      stockWarning ? "font-medium text-clay-600" : "text-ink-500",
                    ].join(" ")}
                  >
                    Existencias totales: {available ?? 0} · {product.sku}
                    {stockWarning
                      ? " · la cantidad supera el stock; la confirmación fallará hasta reponer inventario."
                      : ""}
                  </p>
                )}
              </article>
            );
          })}
        </div>
      </section>

      <section
        aria-label="Resumen del pedido"
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
            <dt className="text-ink-500">IVA</dt>
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
 * Se monta solo al abrirse para que las consultas de catálogo y stock no se
 * ejecuten en cada render de la lista de pedidos.
 */
export default function SalesOrderForm({
  open,
  order,
  onClose,
  onSaved,
}: SalesOrderFormProps) {
  if (!open) {
    return null;
  }
  return (
    <SalesOrderFormContent
      order={order}
      onClose={onClose}
      onSaved={onSaved}
    />
  );
}
