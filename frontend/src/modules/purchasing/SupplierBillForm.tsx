import { useEffect, useMemo, useState } from "react";

import { useProducts } from "../../api/inventory";
import {
  useCreateSupplierBill,
  useGoodsReceipts,
  usePurchaseOrder,
  usePurchaseOrders,
  useSupplierBills,
  useSuppliers,
} from "../../api/purchasing";
import type {
  SupplierBill,
  SupplierBillFilters,
} from "../../api/purchasing";
import { errorHint, errorMessage } from "./errors";
import {
  computeLine,
  formatCents,
  formatDate,
  formatMoney,
  moneyString,
  parseAmount,
  todayIso,
} from "./format";
import PurchasingDialog from "./PurchasingDialog";

interface SupplierBillFormProps {
  open: boolean;
  /** OC preseleccionada desde el listado de órdenes. */
  initialOrderId?: number | null;
  /** Recepción preseleccionada desde el historial de recepciones. */
  initialReceiptId?: number | null;
  onClose: () => void;
  onSaved: (bill: SupplierBill, message: string) => void;
}

interface ContentProps {
  initialOrderId: number | null;
  initialReceiptId: number | null;
  onClose: () => void;
  onSaved: (bill: SupplierBill, message: string) => void;
}

interface ExpectedAmounts {
  subtotalCents: number;
  taxCents: number;
  totalCents: number;
  billedSubtotalCents: number;
  billedTaxCents: number;
  remainingSubtotalCents: number;
  remainingTaxCents: number;
  lines: Array<{
    key: string;
    label: string;
    quantity: number;
    unitPrice: string;
    taxRate: string;
    subtotalCents: number;
    taxCents: number;
  }>;
  taxForSubtotal: (subtotalCents: number) => number;
}

const labelClass = "mb-1.5 block text-xs font-semibold text-ink-700";
const fieldClass =
  "w-full border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-950 " +
  "placeholder:text-concrete-400 focus:border-ink-950";
const secondaryButton =
  "border border-concrete-200 px-4 py-2 text-sm font-semibold text-ink-700 hover:border-ink-500 hover:text-ink-950";
const primaryButton =
  "bg-signal-500 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-signal-600 disabled:cursor-not-allowed disabled:opacity-60";

/** Pydantic serializa `Decimal` como string; convertimos a centavos sin deriva. */
function cents(value: string): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.round(parsed * 100) : 0;
}

function SupplierBillFormContent({
  initialOrderId,
  initialReceiptId,
  onClose,
  onSaved,
}: ContentProps) {
  const [orderId, setOrderId] = useState(
    initialOrderId === null ? "" : String(initialOrderId),
  );
  const [receiptId, setReceiptId] = useState(
    initialReceiptId === null ? "" : String(initialReceiptId),
  );
  const [invoiceNumber, setInvoiceNumber] = useState("");
  const [issueDate, setIssueDate] = useState(todayIso());
  const [dueDate, setDueDate] = useState("");
  const [subtotal, setSubtotal] = useState("");
  const [taxAmount, setTaxAmount] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [linesOpen, setLinesOpen] = useState(false);

  const numericOrderId = Number(orderId);
  const ordersQuery = usePurchaseOrders({ limit: 200 });
  const orderDetailQuery = usePurchaseOrder(
    numericOrderId,
    Number.isInteger(numericOrderId) && numericOrderId > 0,
  );
  const receiptsQuery = useGoodsReceipts({ limit: 200 });
  const suppliersQuery = useSuppliers({ limit: 200 });
  const productsQuery = useProducts({ limit: 200 });
  const billFilters: SupplierBillFilters = { limit: 200 };
  if (Number.isInteger(numericOrderId) && numericOrderId > 0) {
    billFilters.purchase_order_id = numericOrderId;
  }
  const billsQuery = useSupplierBills(billFilters);
  const billMutation = useCreateSupplierBill();

  const orders = ordersQuery.data ?? [];
  const listOrder =
    orders.find((order) => order.id === numericOrderId) ?? null;
  const order = orderDetailQuery.data ?? listOrder;
  const receipts = (receiptsQuery.data ?? []).filter(
    (receipt) => receipt.purchase_order_id === numericOrderId,
  );
  const selectedReceipt =
    receipts.find((receipt) => receipt.id === Number(receiptId)) ?? null;
  const supplier =
    order === null
      ? undefined
      : (suppliersQuery.data ?? []).find(
          (candidate) => candidate.id === order.supplier_id,
        );
  const productById = useMemo(
    () =>
      new Map(
        (productsQuery.data ?? []).map((product) => [product.id, product]),
      ),
    [productsQuery.data],
  );
  const bills = billsQuery.data ?? [];

  /**
   * Reproduce `_expected_bill_amounts` + `_billed_amounts` del servicio:
   * solo se factura lo recibido, restando facturas no anuladas del mismo
   * documento de origen.
   */
  const expected = useMemo<ExpectedAmounts | null>(() => {
    if (order === null) {
      return null;
    }

    let subtotalCents = 0;
    let taxCents = 0;
    const lines: ExpectedAmounts["lines"] = [];

    for (const item of order.items) {
      const quantity =
        selectedReceipt === null
          ? item.received_quantity
          : selectedReceipt.items
              .filter(
                (receiptItem) =>
                  receiptItem.purchase_order_item_id === item.id,
              )
              .reduce((sum, receiptItem) => sum + receiptItem.quantity, 0);
      if (quantity <= 0) {
        continue;
      }
      const unitPrice = Number(item.unit_price);
      const taxRate = Number(item.tax_rate);
      if (!Number.isFinite(unitPrice) || !Number.isFinite(taxRate)) {
        continue;
      }
      const amounts = computeLine(quantity, unitPrice, taxRate);
      subtotalCents += amounts.subtotalCents;
      taxCents += amounts.taxCents;
      const product = productById.get(item.product_id);
      lines.push({
        key: String(item.id),
        label:
          product === undefined
            ? `Producto #${item.product_id}`
            : `${product.sku} — ${product.name}`,
        quantity,
        unitPrice: item.unit_price,
        taxRate: item.tax_rate,
        subtotalCents: amounts.subtotalCents,
        taxCents: amounts.taxCents,
      });
    }

    const activeBills = bills.filter(
      (bill) => bill.purchase_order_id === order.id && bill.status !== "VOID",
    );
    const billedSubtotalCents = activeBills.reduce(
      (sum, bill) => sum + cents(bill.subtotal),
      0,
    );
    const billedTaxCents = activeBills.reduce(
      (sum, bill) => sum + cents(bill.tax_amount),
      0,
    );

    let remainingSubtotalCents = subtotalCents - billedSubtotalCents;
    let remainingTaxCents = taxCents - billedTaxCents;
    if (selectedReceipt !== null) {
      const receiptBills = activeBills.filter(
        (bill) => bill.goods_receipt_id === selectedReceipt.id,
      );
      remainingSubtotalCents = Math.min(
        remainingSubtotalCents,
        subtotalCents -
          receiptBills.reduce((sum, bill) => sum + cents(bill.subtotal), 0),
      );
      remainingTaxCents = Math.min(
        remainingTaxCents,
        taxCents -
          receiptBills.reduce((sum, bill) => sum + cents(bill.tax_amount), 0),
      );
    }

    return {
      subtotalCents,
      taxCents,
      totalCents: subtotalCents + taxCents,
      billedSubtotalCents,
      billedTaxCents,
      remainingSubtotalCents: Math.max(0, remainingSubtotalCents),
      remainingTaxCents: Math.max(0, remainingTaxCents),
      lines,
      taxForSubtotal: (valueCents: number) =>
        subtotalCents === 0
          ? 0
          : Math.round((valueCents * taxCents) / subtotalCents),
    };
  }, [bills, order, productById, selectedReceipt]);

  // Cada vez que cambia el documento de origen se recalculan los importes
  // sugeridos, tal como los validará después el backend.
  useEffect(() => {
    if (expected === null || expected.remainingSubtotalCents <= 0) {
      setSubtotal("");
      setTaxAmount("");
      setFormError(null);
      return;
    }
    setSubtotal(moneyString(expected.remainingSubtotalCents / 100));
    setTaxAmount(
      moneyString(expected.taxForSubtotal(expected.remainingSubtotalCents) / 100),
    );
    setFormError(null);
  }, [expected]);

  function handleSubtotalChange(value: string) {
    setSubtotal(value);
    const parsed = parseAmount(value);
    if (expected !== null && parsed !== null && parsed > 0) {
      setTaxAmount(
        moneyString(expected.taxForSubtotal(Math.round(parsed * 100)) / 100),
      );
    }
  }

  function validate(): string | null {
    if (order === null) {
      return "Selecciona la orden de compra de origen.";
    }
    if (supplier === undefined) {
      return "No se pudo resolver el proveedor de la orden seleccionada.";
    }
    if (!supplier.is_active) {
      return `El proveedor ${supplier.company_name} está inactivo y no admite nuevas facturas.`;
    }
    if (receiptId !== "" && selectedReceipt === null) {
      return "La recepción elegida no pertenece a la orden seleccionada.";
    }
    if (expected === null || expected.subtotalCents <= 0) {
      return "No hay cantidades recibidas para facturar en el documento de origen.";
    }
    if (expected.remainingSubtotalCents <= 0) {
      return "El documento de origen ya está facturado en su totalidad.";
    }
    const trimmedNumber = invoiceNumber.trim();
    if (trimmedNumber === "") {
      return "Indica el número de factura física emitida por el proveedor.";
    }
    if (trimmedNumber.length > 100) {
      return "El número de factura no puede superar 100 caracteres.";
    }
    if (issueDate.trim() === "") {
      return "Indica la fecha de emisión de la factura.";
    }
    if (dueDate !== "" && dueDate < issueDate) {
      return "La fecha de vencimiento no puede ser anterior a la emisión.";
    }

    const subtotalValue = parseAmount(subtotal);
    if (subtotalValue === null || subtotalValue <= 0) {
      return "El subtotal debe ser un importe mayor que cero con hasta dos decimales.";
    }
    const taxValue = parseAmount(taxAmount);
    if (taxValue === null || taxValue < 0) {
      return "Los impuestos deben ser un importe válido con hasta dos decimales.";
    }
    const subtotalValueCents = Math.round(subtotalValue * 100);
    const taxValueCents = Math.round(taxValue * 100);
    if (subtotalValueCents > expected.remainingSubtotalCents + 1) {
      return (
        `El subtotal supera lo pendiente de facturar (${formatCents(
          expected.remainingSubtotalCents,
        )}).`
      );
    }
    if (taxValueCents > expected.remainingTaxCents + 1) {
      return (
        `Los impuestos superan lo pendiente de facturar (${formatCents(
          expected.remainingTaxCents,
        )}).`
      );
    }
    const expectedTaxCents = expected.taxForSubtotal(subtotalValueCents);
    if (Math.abs(taxValueCents - expectedTaxCents) > 1) {
      return (
        `Los impuestos no corresponden a la tasa pactada; para un subtotal de ` +
        `${formatCents(subtotalValueCents)} deberían ser ${formatCents(
          expectedTaxCents,
        )}.`
      );
    }
    return null;
  }

  function handleSubmit() {
    if (order === null) {
      setFormError("Selecciona una orden de compra antes de continuar.");
      return;
    }
    const message = validate();
    if (message !== null) {
      setFormError(message);
      return;
    }
    setFormError(null);

    billMutation.mutate(
      {
        supplier_id: order.supplier_id,
        purchase_order_id: order.id,
        goods_receipt_id: selectedReceipt?.id ?? null,
        supplier_invoice_number: invoiceNumber.trim(),
        issue_date: issueDate,
        due_date: dueDate.trim() === "" ? null : dueDate,
        subtotal: moneyString(parseAmount(subtotal) ?? 0),
        tax_amount: moneyString(parseAmount(taxAmount) ?? 0),
      },
      {
        onSuccess: (bill) =>
          onSaved(
            bill,
            `Factura ${bill.code} registrada por ${formatMoney(
              bill.total,
            )}; vence el ${formatDate(bill.due_date)}.`,
          ),
      },
    );
  }

  const queryError =
    ordersQuery.error ??
    receiptsQuery.error ??
    suppliersQuery.error ??
    productsQuery.error ??
    billsQuery.error;
  const mutationMessage = errorMessage(billMutation.error);
  const visibleError = formError ?? mutationMessage;

  return (
    <PurchasingDialog
      open
      title="Registrar factura de proveedor"
      subtitle="El proveedor se deriva de la OC; los importes se validan contra lo recibido y lo ya facturado."
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose} className={secondaryButton}>
            Cancelar
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={
              billMutation.isPending ||
              expected === null ||
              expected.remainingSubtotalCents <= 0 ||
              ordersQuery.isPending ||
              billsQuery.isPending
            }
            className={primaryButton}
          >
            {billMutation.isPending ? "Registrando…" : "Registrar factura"}
          </button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className={labelClass} htmlFor="bill-order">
            Orden de compra <span className="text-signal-600">*</span>
          </label>
          <select
            id="bill-order"
            className={fieldClass}
            value={orderId}
            onChange={(event) => {
              setOrderId(event.currentTarget.value);
              setReceiptId("");
            }}
          >
            <option value="">Selecciona una OC</option>
            {orders.map((candidate) => {
              const received = candidate.items.reduce(
                (sum, item) => sum + item.received_quantity,
                0,
              );
              return (
                <option key={candidate.id} value={candidate.id}>
                  {candidate.code} · {received} und. recibidas
                </option>
              );
            })}
          </select>
        </div>
        <div>
          <label className={labelClass} htmlFor="bill-receipt">
            Recepción de origen <span className="font-normal text-ink-500">(opcional)</span>
          </label>
          <select
            id="bill-receipt"
            className={fieldClass}
            value={receiptId}
            onChange={(event) => setReceiptId(event.currentTarget.value)}
            disabled={orderId === ""}
          >
            <option value="">Acumulado de todas las recepciones</option>
            {receipts.map((receipt) => (
              <option key={receipt.id} value={receipt.id}>
                {receipt.code} · {formatDate(receipt.receipt_date)}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-ink-500">
            Al elegir una recepción solo se facturan sus líneas.
          </p>
        </div>
      </div>

      <div className="border border-concrete-200 bg-white px-3 py-2.5 text-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-ink-500">
          Proveedor facturador (derivado de la OC)
        </p>
        {supplier === undefined ? (
          <p className="mt-1 text-sm text-ink-500">
            Selecciona una orden para ver el proveedor.
          </p>
        ) : (
          <>
            <p className="mt-1 font-semibold">{supplier.company_name}</p>
            <p className="mt-0.5 text-xs text-ink-500">
              {supplier.tax_id} · plazo {supplier.payment_terms_days} días
              {supplier.is_active ? null : " · INACTIVO"}
            </p>
          </>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <div>
          <label className={labelClass} htmlFor="bill-invoice-number">
            N.º factura del proveedor <span className="text-signal-600">*</span>
          </label>
          <input
            id="bill-invoice-number"
            type="text"
            maxLength={100}
            className={fieldClass}
            value={invoiceNumber}
            onChange={(event) => setInvoiceNumber(event.currentTarget.value)}
            placeholder="Ej. F-2026-0042"
          />
        </div>
        <div>
          <label className={labelClass} htmlFor="bill-issue-date">
            Emisión <span className="text-signal-600">*</span>
          </label>
          <input
            id="bill-issue-date"
            type="date"
            className={fieldClass}
            value={issueDate}
            onChange={(event) => setIssueDate(event.currentTarget.value)}
          />
        </div>
        <div>
          <label className={labelClass} htmlFor="bill-due-date">
            Vencimiento <span className="font-normal text-ink-500">(opcional)</span>
          </label>
          <input
            id="bill-due-date"
            type="date"
            className={fieldClass}
            value={dueDate}
            onChange={(event) => setDueDate(event.currentTarget.value)}
          />
          <p className="mt-1 text-xs text-ink-500">
            Vacío = emisión + plazos del proveedor.
          </p>
        </div>
      </div>

      <section aria-labelledby="bill-amounts-heading">
        <div className="flex items-end justify-between gap-3">
          <div>
            <h3
              id="bill-amounts-heading"
              className="text-sm font-bold tracking-tight"
            >
              Importes facturables
            </h3>
            <p className="mt-0.5 text-xs text-ink-500">
              Sugeridos desde cantidades recibidas, costos pactados y facturas
              anteriores no anuladas.
            </p>
          </div>
          {expected === null || expected.lines.length === 0 ? null : (
            <button
              type="button"
              onClick={() => setLinesOpen((current) => !current)}
              className="shrink-0 text-xs font-semibold text-ink-500 underline-offset-2 hover:text-ink-950 hover:underline"
            >
              {linesOpen ? "Ocultar líneas" : `Ver ${expected.lines.length} línea(s)`}
            </button>
          )}
        </div>

        <dl className="mt-3 grid grid-cols-2 gap-px border border-concrete-200 bg-concrete-200 text-sm sm:grid-cols-4">
          <div className="bg-white px-3 py-2.5">
            <dt className="text-xs font-semibold text-ink-500">Recibido (base)</dt>
            <dd className="mt-0.5 font-semibold tabular-nums">
              {expected === null ? "—" : formatCents(expected.subtotalCents)}
            </dd>
          </div>
          <div className="bg-white px-3 py-2.5">
            <dt className="text-xs font-semibold text-ink-500">Ya facturado</dt>
            <dd className="mt-0.5 font-semibold tabular-nums">
              {expected === null
                ? "—"
                : formatCents(expected.billedSubtotalCents)}
            </dd>
          </div>
          <div className="bg-white px-3 py-2.5">
            <dt className="text-xs font-semibold text-ink-500">Base disponible</dt>
            <dd className="mt-0.5 font-semibold tabular-nums text-signal-600">
              {expected === null
                ? "—"
                : formatCents(expected.remainingSubtotalCents)}
            </dd>
          </div>
          <div className="bg-white px-3 py-2.5">
            <dt className="text-xs font-semibold text-ink-500">Impuestos pendientes</dt>
            <dd className="mt-0.5 font-semibold tabular-nums">
              {expected === null
                ? "—"
                : formatCents(expected.remainingTaxCents)}
            </dd>
          </div>
        </dl>

        {linesOpen && expected !== null ? (
          <ul className="mt-2 divide-y divide-concrete-200 border border-concrete-200 bg-white">
            {expected.lines.map((line) => (
              <li
                key={line.key}
                className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-xs"
              >
                <span className="min-w-0">
                  <span className="block truncate font-medium text-ink-950">
                    {line.label}
                  </span>
                  <span className="text-ink-500">
                    {line.quantity} × {formatMoney(line.unitPrice)} · imp.{" "}
                    {line.taxRate}%
                  </span>
                </span>
                <span className="font-semibold tabular-nums">
                  {formatCents(line.subtotalCents + line.taxCents)}
                </span>
              </li>
            ))}
          </ul>
        ) : null}

        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          <div>
            <label className={labelClass} htmlFor="bill-subtotal">
              Subtotal <span className="text-signal-600">*</span>
            </label>
            <input
              id="bill-subtotal"
              type="text"
              inputMode="decimal"
              className={fieldClass}
              value={subtotal}
              onChange={(event) => handleSubtotalChange(event.currentTarget.value)}
              autoComplete="off"
            />
          </div>
          <div>
            <label className={labelClass} htmlFor="bill-tax">
              Impuestos
            </label>
            <input
              id="bill-tax"
              type="text"
              inputMode="decimal"
              className={fieldClass}
              value={taxAmount}
              onChange={(event) => setTaxAmount(event.currentTarget.value)}
              autoComplete="off"
            />
            <p className="mt-1 text-xs text-ink-500">
              Se ajustan a la tasa pactada al cambiar el subtotal.
            </p>
          </div>
          <div>
            <span className={labelClass}>Total (calculado)</span>
            <p className="border border-concrete-200 bg-concrete-100 px-3 py-2 text-sm font-semibold tabular-nums text-ink-700">
              {formatCents(
                (parseAmount(subtotal) === null
                  ? 0
                  : Math.round((parseAmount(subtotal) ?? 0) * 100)) +
                  (parseAmount(taxAmount) === null
                    ? 0
                    : Math.round((parseAmount(taxAmount) ?? 0) * 100)),
              )}
            </p>
          </div>
        </div>
        <p className="mt-1 text-xs text-ink-500">
          Puedes facturar por partes: el backend recalcula el total y rechaza
          excesos sobre el saldo del documento.
        </p>
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
          {formError === null && mutationMessage !== null ? (
            <p className="mt-1 font-normal">
              {errorHint(mutationMessage) ??
                "Revisa los datos y vuelve a intentarlo."}
            </p>
          ) : null}
        </div>
      )}
    </PurchasingDialog>
  );
}

/**
 * Alta de cuentas por pagar. Se monta solo al abrirse para que las consultas de
 * apoyo no se ejecuten en cada render de la vista que lo invoca.
 */
export default function SupplierBillForm({
  open,
  initialOrderId = null,
  initialReceiptId = null,
  onClose,
  onSaved,
}: SupplierBillFormProps) {
  if (!open) {
    return null;
  }
  return (
    <SupplierBillFormContent
      initialOrderId={initialOrderId}
      initialReceiptId={initialReceiptId}
      onClose={onClose}
      onSaved={onSaved}
    />
  );
}
