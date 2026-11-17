import { useState } from "react";

import { usePaySupplierBill } from "../../api/purchasing";
import type { SupplierBill } from "../../api/purchasing";
import { canPayBill } from "./constants";
import { errorHint, errorMessage } from "./errors";
import { formatMoney, moneyString, parseAmount, todayIso } from "./format";
import PurchasingDialog from "./PurchasingDialog";

interface BillPaymentFormProps {
  open: boolean;
  bill: SupplierBill | null;
  onClose: () => void;
  onDone: (message: string) => void;
}

interface ContentProps {
  bill: SupplierBill;
  onClose: () => void;
  onDone: (message: string) => void;
}

const labelClass = "mb-1.5 block text-xs font-semibold text-ink-700";
const fieldClass =
  "w-full border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-950 " +
  "placeholder:text-concrete-400 focus:border-ink-950";

function BillPaymentContent({ bill, onClose, onDone }: ContentProps) {
  const [amount, setAmount] = useState(bill.balance_due);
  const [paidAt, setPaidAt] = useState(todayIso());
  const [reference, setReference] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  const paymentMutation = usePaySupplierBill();
  const balanceCents = Math.round(Number(bill.balance_due) * 100);
  const canPay = canPayBill(bill.status) && balanceCents > 0;

  const mutationMessage = errorMessage(paymentMutation.error);
  const visibleError = formError ?? mutationMessage;

  function handleSubmit() {
    if (!canPay) {
      setFormError("Solo las facturas pendientes o pagadas a medias admiten abonos.");
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
          bill.balance_due,
        )}).`,
      );
      return;
    }
    if (paidAt.trim() === "") {
      setFormError("Indica la fecha en que se realizó el pago.");
      return;
    }
    if (reference.trim().length > 100) {
      setFormError("La referencia no puede superar 100 caracteres.");
      return;
    }
    setFormError(null);

    const trimmedReference = reference.trim();
    paymentMutation.mutate(
      {
        billId: bill.id,
        payload: {
          amount: moneyString(parsed),
          paid_at: paidAt,
          reference: trimmedReference === "" ? null : trimmedReference,
        },
      },
      {
        onSuccess: (updated) =>
          onDone(
            `Abono de ${formatMoney(moneyString(parsed))} aplicado a ${
              updated.code
            }; saldo ${formatMoney(updated.balance_due)}.`,
          ),
      },
    );
  }

  return (
    <PurchasingDialog
      open
      title={`Registrar abono · ${bill.code}`}
      subtitle="El pago reduce el saldo y cierra la factura al cubrirlo; el historial es inmutable."
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
            disabled={paymentMutation.isPending || !canPay}
            className="bg-signal-500 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-signal-600 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {paymentMutation.isPending ? "Registrando…" : "Registrar abono"}
          </button>
        </>
      }
    >
      <dl className="grid grid-cols-2 gap-px border border-concrete-200 bg-concrete-200 text-sm">
        <div className="bg-white px-3 py-2.5">
          <dt className="text-xs font-semibold text-ink-500">Total de la factura</dt>
          <dd className="mt-0.5 font-semibold tabular-nums">
            {formatMoney(bill.total)}
          </dd>
        </div>
        <div className="bg-white px-3 py-2.5">
          <dt className="text-xs font-semibold text-ink-500">Saldo pendiente</dt>
          <dd className="mt-0.5 font-semibold tabular-nums text-signal-600">
            {formatMoney(bill.balance_due)}
          </dd>
        </div>
      </dl>

      {canPay ? null : (
        <div
          role="alert"
          className="border-l-2 border-clay-600 bg-clay-100 px-3 py-2 text-sm font-medium text-clay-600"
        >
          Esta factura no admite abonos en su estado actual o ya está saldada.
        </div>
      )}

      <div>
        <div className="mb-1.5 flex items-center justify-between gap-3">
          <label className={labelClass} htmlFor="bill-payment-amount">
            Importe del abono <span className="text-signal-600">*</span>
          </label>
          <button
            type="button"
            onClick={() => setAmount(bill.balance_due)}
            disabled={!canPay}
            className="text-xs font-semibold text-ink-500 underline-offset-2 hover:text-ink-950 hover:underline disabled:cursor-not-allowed disabled:opacity-40"
          >
            Usar saldo total
          </button>
        </div>
        <input
          id="bill-payment-amount"
          type="text"
          inputMode="decimal"
          className={fieldClass}
          value={amount}
          onChange={(event) => setAmount(event.currentTarget.value)}
          autoComplete="off"
        />
        <p className="mt-1 text-xs text-ink-500">
          Se aceptan coma o punto decimal. El backend rechaza sobrepagos.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label className={labelClass} htmlFor="bill-payment-date">
            Fecha de pago <span className="text-signal-600">*</span>
          </label>
          <input
            id="bill-payment-date"
            type="date"
            className={fieldClass}
            value={paidAt}
            onChange={(event) => setPaidAt(event.currentTarget.value)}
          />
        </div>
        <div>
          <label className={labelClass} htmlFor="bill-payment-reference">
            Referencia <span className="font-normal text-ink-500">(opcional)</span>
          </label>
          <input
            id="bill-payment-reference"
            type="text"
            maxLength={100}
            className={fieldClass}
            value={reference}
            onChange={(event) => setReference(event.currentTarget.value)}
            placeholder="Se usa tu usuario si se deja vacía"
          />
        </div>
      </div>

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

/** Abono parcial o total sobre una cuenta por pagar. */
export default function BillPaymentForm({
  open,
  bill,
  onClose,
  onDone,
}: BillPaymentFormProps) {
  if (!open || bill === null) {
    return null;
  }
  return <BillPaymentContent bill={bill} onClose={onClose} onDone={onDone} />;
}
