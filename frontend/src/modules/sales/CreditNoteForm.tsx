import { useState } from "react";

import { useIssueCreditNote } from "../../api/sales";
import type { CreditNoteCreate, Invoice } from "../../api/sales";
import { errorHint, errorMessage } from "./errors";
import { formatMoney, moneyString, parseAmount, todayIso } from "./format";
import SalesDialog from "./SalesDialog";

interface CreditNoteFormProps {
  open: boolean;
  invoice: Invoice | null;
  /** Suma de notas crédito ya emitidas sobre la factura. */
  credited: number;
  onClose: () => void;
  onDone: (message: string) => void;
}

interface CreditNoteContentProps {
  invoice: Invoice;
  credited: number;
  onClose: () => void;
  onDone: (message: string) => void;
}

function CreditNoteContent({
  invoice,
  credited,
  onClose,
  onDone,
}: CreditNoteContentProps) {
  const totalCents = Math.round(Number(invoice.total) * 100);
  const creditedCents = Math.round(credited * 100);
  const creditableCents = Math.max(0, totalCents - creditedCents);
  const canCredit = invoice.status !== "VOID" && creditableCents > 0;

  const [amount, setAmount] = useState((creditableCents / 100).toFixed(2));
  const [reason, setReason] = useState("");
  const [issueDate, setIssueDate] = useState(todayIso());
  const [formError, setFormError] = useState<string | null>(null);

  const creditNoteMutation = useIssueCreditNote();

  const mutationMessage = errorMessage(creditNoteMutation.error);
  const mutationHint =
    mutationMessage === null ? null : errorHint(mutationMessage);
  const visibleError = formError ?? mutationMessage;

  function handleSubmit() {
    if (!canCredit) {
      setFormError(
        "La factura está anulada o ya fue acreditada por su totalidad.",
      );
      return;
    }
    if (issueDate === "") {
      setFormError("Indica la fecha de emisión de la nota.");
      return;
    }
    const parsed = parseAmount(amount);
    if (parsed === null) {
      setFormError("Escribe un importe válido con hasta dos decimales.");
      return;
    }
    const amountCents = Math.round(parsed * 100);
    if (amountCents <= 0) {
      setFormError("El importe de la nota debe ser mayor que cero.");
      return;
    }
    if (amountCents > creditableCents) {
      setFormError(
        `La nota no puede superar el importe acreditable (${formatMoney(
          creditableCents / 100,
        )}).`,
      );
      return;
    }
    setFormError(null);

    const payload: CreditNoteCreate = {
      amount: moneyString(parsed),
      issue_date: issueDate,
      reason: reason.trim() === "" ? null : reason.trim(),
    };
    creditNoteMutation.mutate(
      { invoiceId: invoice.id, payload },
      {
        onSuccess: (note) =>
          onDone(
            `Nota crédito ${note.code} emitida por ${formatMoney(
              note.amount,
            )} sobre ${invoice.code}.`,
          ),
      },
    );
  }

  return (
    <SalesDialog
      open
      title={`Nota crédito · ${invoice.code}`}
      subtitle="Registra una devolución o descuento sin modificar ni borrar la factura."
      onClose={onClose}
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="border border-concrete-200 px-4 py-2 text-sm font-semibold text-ink-700 hover:border-ink-500 hover:text-ink-950"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={creditNoteMutation.isPending || !canCredit}
            className="bg-signal-500 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-signal-600 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {creditNoteMutation.isPending ? "Emitiendo…" : "Emitir nota crédito"}
          </button>
        </>
      }
    >
      <dl className="grid grid-cols-3 gap-px border border-concrete-200 bg-concrete-200 text-sm">
        <div className="bg-white px-3 py-2.5">
          <dt className="text-xs font-semibold text-ink-500">Total</dt>
          <dd className="mt-0.5 font-semibold tabular-nums">
            {formatMoney(invoice.total)}
          </dd>
        </div>
        <div className="bg-white px-3 py-2.5">
          <dt className="text-xs font-semibold text-ink-500">Acreditado</dt>
          <dd className="mt-0.5 font-semibold tabular-nums">
            {formatMoney(creditedCents / 100)}
          </dd>
        </div>
        <div className="bg-white px-3 py-2.5">
          <dt className="text-xs font-semibold text-ink-500">Acreditable</dt>
          <dd className="mt-0.5 font-semibold tabular-nums text-signal-600">
            {formatMoney(creditableCents / 100)}
          </dd>
        </div>
      </dl>

      {canCredit ? null : (
        <div
          role="alert"
          className="border-l-2 border-clay-600 bg-clay-100 px-3 py-2 text-sm font-medium text-clay-600"
        >
          Esta factura ya no tiene importe acreditable disponible.
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <div className="mb-1.5 flex items-center justify-between gap-3">
            <label
              className="block text-xs font-semibold text-ink-700"
              htmlFor="credit-note-amount"
            >
              Importe a acreditar <span className="text-signal-600">*</span>
            </label>
            <button
              type="button"
              onClick={() => setAmount((creditableCents / 100).toFixed(2))}
              disabled={!canCredit}
              className="text-xs font-semibold text-ink-500 underline-offset-2 hover:text-ink-950 hover:underline disabled:cursor-not-allowed disabled:opacity-40"
            >
              Acreditar todo
            </button>
          </div>
          <input
            id="credit-note-amount"
            type="text"
            inputMode="decimal"
            value={amount}
            onChange={(event) => setAmount(event.currentTarget.value)}
            autoComplete="off"
            className="w-full border border-concrete-200 bg-white px-3 py-2 text-sm tabular-nums text-ink-950 focus:border-ink-950"
          />
        </div>
        <div>
          <label
            className="mb-1.5 block text-xs font-semibold text-ink-700"
            htmlFor="credit-note-date"
          >
            Fecha de emisión <span className="text-signal-600">*</span>
          </label>
          <input
            id="credit-note-date"
            type="date"
            value={issueDate}
            onChange={(event) => setIssueDate(event.currentTarget.value)}
            className="w-full border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-950 focus:border-ink-950"
          />
        </div>
      </div>

      <div>
        <label
          className="mb-1.5 block text-xs font-semibold text-ink-700"
          htmlFor="credit-note-reason"
        >
          Motivo
        </label>
        <textarea
          id="credit-note-reason"
          rows={3}
          value={reason}
          onChange={(event) => setReason(event.currentTarget.value)}
          placeholder="Devolución de mercancía, descuento comercial…"
          className="w-full resize-y border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-950 placeholder:text-concrete-400 focus:border-ink-950"
        />
        <p className="mt-1 text-xs text-ink-500">
          El código NC-AAAA-0000 se genera automáticamente. El acumulado de
          notas nunca puede superar el total facturado.
        </p>
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

/** Emite una nota crédito por devolución o descuento sobre una factura. */
export default function CreditNoteForm({
  open,
  invoice,
  credited,
  onClose,
  onDone,
}: CreditNoteFormProps) {
  if (!open || invoice === null) {
    return null;
  }
  return (
    <CreditNoteContent
      invoice={invoice}
      credited={credited}
      onClose={onClose}
      onDone={onDone}
    />
  );
}
