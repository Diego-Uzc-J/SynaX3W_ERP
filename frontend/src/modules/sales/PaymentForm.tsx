import { useState } from "react";

import { useRegisterInvoicePayment } from "../../api/sales";
import type { Invoice } from "../../api/sales";
import { errorHint, errorMessage } from "./errors";
import { formatMoney, moneyString, parseAmount } from "./format";
import SalesDialog from "./SalesDialog";

interface PaymentFormProps {
  open: boolean;
  invoice: Invoice | null;
  onClose: () => void;
  onDone: (message: string) => void;
}

interface PaymentContentProps {
  invoice: Invoice;
  onClose: () => void;
  onDone: (message: string) => void;
}

function PaymentContent({ invoice, onClose, onDone }: PaymentContentProps) {
  const [amount, setAmount] = useState(invoice.balance_due);
  const [formError, setFormError] = useState<string | null>(null);

  const paymentMutation = useRegisterInvoicePayment();

  const balanceCents = Math.round(Number(invoice.balance_due) * 100);
  const canPay = invoice.status === "ISSUED" && balanceCents > 0;

  const mutationMessage = errorMessage(paymentMutation.error);
  const mutationHint =
    mutationMessage === null ? null : errorHint(mutationMessage);
  const visibleError = formError ?? mutationMessage;

  function handleSubmit() {
    if (!canPay) {
      setFormError("Solo las facturas emitidas con saldo pendiente admiten abonos.");
      return;
    }
    const parsed = parseAmount(amount);
    if (parsed === null) {
      setFormError("Escribe un importe válido con hasta dos decimales.");
      return;
    }
    const amountCents = Math.round(parsed * 100);
    if (amountCents <= 0) {
      setFormError("El abono debe ser mayor que cero.");
      return;
    }
    if (amountCents > balanceCents) {
      setFormError(
        `El abono no puede superar el saldo pendiente (${formatMoney(
          invoice.balance_due,
        )}).`,
      );
      return;
    }
    setFormError(null);

    paymentMutation.mutate(
      {
        invoiceId: invoice.id,
        payload: { amount: moneyString(parsed) },
      },
      {
        onSuccess: (updated) =>
          onDone(
            `Abono de ${formatMoney(moneyString(parsed))} registrado en ${
              updated.code
            }; saldo ${formatMoney(updated.balance_due)}.`,
          ),
      },
    );
  }

  return (
    <SalesDialog
      open
      title={`Registrar abono · ${invoice.code}`}
      subtitle="El pago reduce el saldo pendiente y pasa la factura a PAID al cubrirlo."
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
            disabled={
              paymentMutation.isPending || !canPay || balanceCents === 0
            }
            className="bg-signal-500 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-signal-600 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {paymentMutation.isPending ? "Registrando…" : "Registrar abono"}
          </button>
        </>
      }
    >
      <dl className="grid grid-cols-2 gap-px border border-concrete-200 bg-concrete-200 text-sm">
        <div className="bg-white px-3 py-2.5">
          <dt className="text-xs font-semibold text-ink-500">Total facturado</dt>
          <dd className="mt-0.5 font-semibold tabular-nums">
            {formatMoney(invoice.total)}
          </dd>
        </div>
        <div className="bg-white px-3 py-2.5">
          <dt className="text-xs font-semibold text-ink-500">Saldo pendiente</dt>
          <dd className="mt-0.5 font-semibold tabular-nums text-signal-600">
            {formatMoney(invoice.balance_due)}
          </dd>
        </div>
      </dl>

      {canPay ? null : (
        <div
          role="alert"
          className="border-l-2 border-clay-600 bg-clay-100 px-3 py-2 text-sm font-medium text-clay-600"
        >
          Esta factura no admite abonos en su estado actual.
        </div>
      )}

      <div>
        <div className="mb-1.5 flex items-center justify-between gap-3">
          <label
            className="block text-xs font-semibold text-ink-700"
            htmlFor="payment-amount"
          >
            Importe del abono <span className="text-signal-600">*</span>
          </label>
          <button
            type="button"
            onClick={() => setAmount(invoice.balance_due)}
            disabled={!canPay}
            className="text-xs font-semibold text-ink-500 underline-offset-2 hover:text-ink-950 hover:underline disabled:cursor-not-allowed disabled:opacity-40"
          >
            Usar saldo total
          </button>
        </div>
        <input
          id="payment-amount"
          type="text"
          inputMode="decimal"
          value={amount}
          onChange={(event) => setAmount(event.currentTarget.value)}
          autoComplete="off"
          className="w-full border border-concrete-200 bg-white px-3 py-2 text-sm tabular-nums text-ink-950 focus:border-ink-950"
        />
        <p className="mt-1 text-xs text-ink-500">
          Se aceptan coma o punto decimal. El backend rechaza sobrepagos.
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

/** Registra un abono parcial o total sobre una factura emitida. */
export default function PaymentForm({
  open,
  invoice,
  onClose,
  onDone,
}: PaymentFormProps) {
  if (!open || invoice === null) {
    return null;
  }
  return <PaymentContent invoice={invoice} onClose={onClose} onDone={onDone} />;
}
