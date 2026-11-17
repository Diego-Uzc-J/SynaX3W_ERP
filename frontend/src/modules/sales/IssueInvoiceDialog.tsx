import { useState } from "react";

import { useInvoices, useIssueInvoice } from "../../api/sales";
import type { InvoiceCreate, SalesOrder } from "../../api/sales";
import { errorHint, errorMessage } from "./errors";
import { formatMoney, todayIso, todayPlusDays } from "./format";
import SalesDialog from "./SalesDialog";

interface IssueInvoiceDialogProps {
  open: boolean;
  order: SalesOrder | null;
  onClose: () => void;
  onDone: (message: string) => void;
}

interface InvoiceContentProps {
  order: SalesOrder;
  onClose: () => void;
  onDone: (message: string) => void;
}

function IssueInvoiceContent({ order, onClose, onDone }: InvoiceContentProps) {
  const [issueDate, setIssueDate] = useState(todayIso());
  const [dueDate, setDueDate] = useState(todayPlusDays(30));
  const [formError, setFormError] = useState<string | null>(null);

  const invoicesQuery = useInvoices({ sales_order_id: order.id, limit: 200 });
  const invoiceMutation = useIssueInvoice();

  const activeInvoices = (invoicesQuery.data ?? []).filter(
    (invoice) => invoice.status !== "VOID",
  );
  const hasActiveInvoice = activeInvoices.length > 0;

  const mutationMessage = errorMessage(invoiceMutation.error);
  const mutationHint =
    mutationMessage === null ? null : errorHint(mutationMessage);
  const visibleError = formError ?? mutationMessage;

  const submitDisabled =
    hasActiveInvoice || invoiceMutation.isPending || invoicesQuery.isPending;

  function handleSubmit() {
    if (issueDate === "") {
      setFormError("Indica la fecha de emisión.");
      return;
    }
    if (dueDate === "") {
      setFormError("Indica la fecha límite de pago.");
      return;
    }
    if (dueDate < issueDate) {
      setFormError(
        "La fecha límite de pago no puede ser anterior a la emisión.",
      );
      return;
    }
    setFormError(null);

    const payload: InvoiceCreate = {
      sales_order_id: order.id,
      customer_id: order.customer_id,
      issue_date: issueDate,
      due_date: dueDate,
    };
    invoiceMutation.mutate(payload, {
      onSuccess: (invoice) =>
        onDone(
          `Factura ${invoice.code} emitida por ${formatMoney(invoice.total)}.`,
        ),
    });
  }

  return (
    <SalesDialog
      open
      title={`Facturar pedido ${order.code}`}
      subtitle="El total se toma del pedido y la factura queda inmutable al emitirse."
      onClose={onClose}
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="border border-concrete-200 px-4 py-2 text-sm font-semibold text-ink-700 hover:border-ink-500 hover:text-ink-950"
          >
            Volver
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitDisabled}
            className="bg-signal-500 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-signal-600 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {invoiceMutation.isPending ? "Emitiendo…" : "Emitir factura"}
          </button>
        </>
      }
    >
      <dl className="grid grid-cols-2 gap-px border border-concrete-200 bg-concrete-200 text-sm">
        <div className="bg-white px-3 py-2.5">
          <dt className="text-xs font-semibold text-ink-500">Pedido</dt>
          <dd className="mt-0.5 font-semibold tabular-nums">{order.code}</dd>
        </div>
        <div className="bg-white px-3 py-2.5">
          <dt className="text-xs font-semibold text-ink-500">
            Total a facturar
          </dt>
          <dd className="mt-0.5 font-semibold tabular-nums">
            {formatMoney(order.total)}
          </dd>
        </div>
      </dl>

      <p className="text-xs text-ink-500">
        El código se genera automáticamente con formato FAC-AAAA-0000. El saldo
        inicial será igual al total y podrá pagarse parcial o totalmente.
      </p>

      {invoicesQuery.error !== null ? (
        <p className="border-l-2 border-clay-600 bg-clay-100 px-3 py-2 text-xs font-medium text-clay-600">
          No se pudieron consultar las facturas del pedido
          ({invoicesQuery.error.message}). El servidor rechazará la emisión si
          ya existe una factura vigente.
        </p>
      ) : hasActiveInvoice ? (
        <div
          role="alert"
          className="border-l-2 border-signal-500 bg-signal-100 px-3 py-2 text-sm font-medium text-signal-600"
        >
          <p className="font-semibold">
            El pedido ya tiene una factura vigente
            {activeInvoices[0] === undefined
              ? ""
              : ` (${activeInvoices[0].code})`}
            .
          </p>
          <p className="mt-1">
            Para corregirla, anúlala con VOID o emite una nota crédito. Una
            segunda factura duplicaría la cuenta por cobrar.
          </p>
        </div>
      ) : invoicesQuery.isPending ? (
        <p className="text-xs text-ink-500">Verificando facturas existentes…</p>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label
            className="mb-1.5 block text-xs font-semibold text-ink-700"
            htmlFor="invoice-issue-date"
          >
            Fecha de emisión <span className="text-signal-600">*</span>
          </label>
          <input
            id="invoice-issue-date"
            type="date"
            value={issueDate}
            onChange={(event) => setIssueDate(event.currentTarget.value)}
            className="w-full border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-950 focus:border-ink-950"
          />
        </div>
        <div>
          <label
            className="mb-1.5 block text-xs font-semibold text-ink-700"
            htmlFor="invoice-due-date"
          >
            Límite de pago <span className="text-signal-600">*</span>
          </label>
          <input
            id="invoice-due-date"
            type="date"
            value={dueDate}
            onChange={(event) => setDueDate(event.currentTarget.value)}
            className="w-full border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-950 focus:border-ink-950"
          />
        </div>
      </div>

      {visibleError === null ? null : (
        <div
          role="alert"
          className="border-l-2 border-signal-500 bg-signal-100 px-3 py-2 text-sm font-medium text-signal-600"
        >
          <p>{visibleError}</p>
          {mutationHint === null ? null : (
            <p className="mt-1 font-normal">{mutationHint}</p>
          )}
        </div>
      )}
    </SalesDialog>
  );
}

/** Emite la factura fiscal de un pedido confirmado o entregado. */
export default function IssueInvoiceDialog({
  open,
  order,
  onClose,
  onDone,
}: IssueInvoiceDialogProps) {
  if (!open || order === null) {
    return null;
  }
  return (
    <IssueInvoiceContent order={order} onClose={onClose} onDone={onDone} />
  );
}
