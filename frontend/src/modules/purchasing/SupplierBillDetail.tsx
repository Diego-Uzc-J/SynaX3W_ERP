import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  useBillPayments,
  useGoodsReceipts,
  usePurchaseOrders,
  useSupplierBill,
  useSuppliers,
  useVoidSupplierBill,
} from "../../api/purchasing";
import type { SupplierBillPayment } from "../../api/purchasing";
import { canWriteModule, useAuth } from "../../store/authStore";
import {
  BILL_STATUS_HINTS,
  BILL_STATUS_LABELS,
  canPayBill,
  canVoidBill,
} from "./constants";
import { errorHint, errorMessage } from "./errors";
import { formatDate, formatMoney, todayIso } from "./format";
import BillPaymentForm from "./BillPaymentForm";
import PurchasingDialog from "./PurchasingDialog";
import PurchasingTabs from "./PurchasingTabs";
import { BillStatusBadge } from "./PurchasingStatusBadge";

interface Feedback {
  tone: "success" | "error";
  text: string;
}

function SummaryCard({
  label,
  value,
  hint,
  emphasis = false,
}: {
  label: string;
  value: string;
  hint?: string | undefined;
  emphasis?: boolean | undefined;
}) {
  return (
    <div className="bg-white px-4 py-3">
      <dt className="text-xs font-semibold text-ink-500">{label}</dt>
      <dd
        className={[
          "mt-1 text-xl font-extrabold tabular-nums sm:text-2xl",
          emphasis ? "text-signal-600" : "text-ink-950",
        ].join(" ")}
      >
        {value}
      </dd>
      {hint === undefined ? null : (
        <dd className="mt-0.5 text-xs text-ink-500">{hint}</dd>
      )}
    </div>
  );
}

function PaymentsTable({
  payments,
  isPending,
}: {
  payments: SupplierBillPayment[];
  isPending: boolean;
}) {
  if (isPending) {
    return (
      <p className="border border-concrete-200 bg-white px-4 py-6 text-sm text-ink-500">
        Cargando historial de abonos…
      </p>
    );
  }
  if (payments.length === 0) {
    return (
      <p className="border border-dashed border-concrete-200 bg-white px-4 py-6 text-sm text-ink-500">
        Todavía no se han registrado abonos sobre esta factura.
      </p>
    );
  }
  return (
    <div className="border border-concrete-200 bg-white">
      <table className="w-full border-collapse text-left text-sm">
        <thead>
          <tr className="border-b border-concrete-200 text-xs font-semibold text-ink-500">
            <th scope="col" className="px-4 py-2.5">
              Fecha de pago
            </th>
            <th scope="col" className="px-4 py-2.5">
              Referencia
            </th>
            <th scope="col" className="px-4 py-2.5">
              Registrado
            </th>
            <th scope="col" className="px-4 py-2.5 text-right">
              Importe
            </th>
          </tr>
        </thead>
        <tbody>
          {[...payments].reverse().map((payment) => (
            <tr
              key={payment.id}
              className="border-b border-concrete-100 last:border-b-0"
            >
              <td className="px-4 py-2.5 text-xs text-ink-700">
                {formatDate(payment.paid_at)}
              </td>
              <td className="px-4 py-2.5 text-xs text-ink-700">
                {payment.reference ?? "—"}
              </td>
              <td className="px-4 py-2.5 text-xs tabular-nums text-ink-500">
                {payment.created_at.slice(0, 10)}
              </td>
              <td className="px-4 py-2.5 text-right font-semibold tabular-nums">
                {formatMoney(payment.amount)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function SupplierBillDetail() {
  const { billId: rawBillId } = useParams();
  const billId = Number(rawBillId);
  const validId = Number.isInteger(billId) && billId > 0;

  const { user } = useAuth();
  const canWrite = canWriteModule(user, "purchasing");

  const billQuery = useSupplierBill(billId, validId);
  const paymentsQuery = useBillPayments(billId, validId);
  const suppliersQuery = useSuppliers({ limit: 200 });
  const ordersQuery = usePurchaseOrders({ limit: 200 });
  const receiptsQuery = useGoodsReceipts({ limit: 200 });
  const voidMutation = useVoidSupplierBill();

  const [paymentOpen, setPaymentOpen] = useState(false);
  const [voidOpen, setVoidOpen] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  if (!validId || billQuery.error !== null) {
    const message = billQuery.error?.message ?? "El identificador de la factura no es válido.";
    return (
      <div className="mx-auto w-full max-w-[1200px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
        <div className="border border-signal-500/40 bg-signal-100 px-5 py-6">
          <p className="text-sm font-semibold text-signal-600">
            No se pudo cargar la factura.
          </p>
          <p className="mt-1 text-sm text-ink-700">{message}</p>
          <div className="mt-4 flex flex-wrap gap-2">
            {billQuery.error !== null && validId ? (
              <button
                type="button"
                onClick={() => void billQuery.refetch()}
                className="border border-signal-500 px-3 py-1.5 text-sm font-semibold text-signal-600 hover:bg-signal-500 hover:text-white"
              >
                Reintentar
              </button>
            ) : null}
            <Link
              to="/purchasing/bills"
              className="border border-concrete-200 px-3 py-1.5 text-sm font-semibold text-ink-700 hover:border-ink-950 hover:text-ink-950"
            >
              Volver a facturas
            </Link>
          </div>
        </div>
      </div>
    );
  }

  const bill = billQuery.data;
  if (bill === undefined) {
    return (
      <div className="mx-auto w-full max-w-[1200px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
        <div className="h-10 w-64 animate-pulse bg-concrete-100" />
        <div className="mt-6 h-28 animate-pulse border border-concrete-200 bg-white" />
        <div className="mt-5 h-48 animate-pulse border border-concrete-200 bg-white" />
      </div>
    );
  }

  const supplier = (suppliersQuery.data ?? []).find(
    (item) => item.id === bill.supplier_id,
  );
  const order = (ordersQuery.data ?? []).find(
    (item) => item.id === bill.purchase_order_id,
  );
  const receipt = (receiptsQuery.data ?? []).find(
    (item) => item.id === bill.goods_receipt_id,
  );

  const totalCents = Math.round(Number(bill.total) * 100);
  const balanceCents = Math.round(Number(bill.balance_due) * 100);
  const paidCents =
    bill.status === "VOID" ? 0 : Math.max(0, totalCents - balanceCents);
  const isOverdue = canPayBill(bill.status) && bill.due_date < todayIso();
  const canPay = canWrite && canPayBill(bill.status) && balanceCents > 0;
  const canVoid = canWrite && canVoidBill(bill.status);

  const mutationMessage = errorMessage(voidMutation.error);

  function handlePaymentDone(message: string) {
    setFeedback({ tone: "success", text: message });
    setPaymentOpen(false);
  }

  function handleVoid(billIdToVoid: number) {
    voidMutation.mutate(billIdToVoid, {
      onSuccess: (updated) => {
        setFeedback({
          tone: "success",
          text: `Factura ${updated.code} anulada; el historial se conserva.`,
        });
        setVoidOpen(false);
      },
    });
  }

  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
      <Link
        to="/purchasing/bills"
        className="text-xs font-semibold text-ink-500 underline-offset-2 hover:text-ink-950 hover:underline"
      >
        ← Volver a facturas
      </Link>

      <header className="mt-4 flex flex-col gap-5 border-b-2 border-ink-950 pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-signal-600">
              Cuenta por pagar
            </p>
            <BillStatusBadge status={bill.status} />
          </div>
          <h1 className="mt-2 text-4xl font-extrabold tracking-tight tabular-nums sm:text-5xl">
            {bill.code}
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-700">
            {supplier?.company_name ?? `Proveedor #${bill.supplier_id}`} · N.º{" "}
            {bill.supplier_invoice_number} · {BILL_STATUS_HINTS[bill.status]}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {canPay ? (
            <button
              type="button"
              onClick={() => setPaymentOpen(true)}
              className="bg-signal-500 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-signal-600"
            >
              Registrar abono
            </button>
          ) : null}
          {canVoid ? (
            <button
              type="button"
              onClick={() => setVoidOpen(true)}
              className="border border-concrete-200 px-4 py-2.5 text-sm font-semibold text-ink-700 hover:border-signal-500 hover:text-signal-600"
            >
              Anular
            </button>
          ) : null}
          {!canPay && !canVoid ? (
            <span className="text-xs text-concrete-400">
              {canWrite ? "Sin acciones disponibles" : "Solo lectura"}
            </span>
          ) : null}
        </div>
      </header>

      <PurchasingTabs />

      {feedback === null ? null : (
        <div
          role="status"
          className="mt-5 flex items-start justify-between gap-4 border border-pine-600/30 bg-pine-100 px-4 py-3 text-sm font-medium text-pine-600"
        >
          <p>{feedback.text}</p>
          <button
            type="button"
            onClick={() => setFeedback(null)}
            className="text-base leading-none hover:text-ink-950"
            aria-label="Cerrar aviso"
          >
            ×
          </button>
        </div>
      )}

      <dl className="mt-6 grid grid-cols-2 divide-x divide-concrete-200 border border-concrete-200 bg-white lg:grid-cols-4">
        <SummaryCard label="Subtotal" value={formatMoney(bill.subtotal)} />
        <SummaryCard label="Impuestos" value={formatMoney(bill.tax_amount)} />
        <SummaryCard
          label="Abonado"
          value={formatMoney(paidCents / 100)}
          hint={bill.status === "VOID" ? "Anulada" : undefined}
        />
        <SummaryCard
          label="Saldo pendiente"
          value={formatMoney(bill.balance_due)}
          emphasis={balanceCents > 0 && bill.status !== "VOID"}
          hint={isOverdue ? `Vencida el ${formatDate(bill.due_date)}` : undefined}
        />
      </dl>

      <section className="mt-6" aria-labelledby="bill-source-heading">
        <h2
          id="bill-source-heading"
          className="text-sm font-bold tracking-tight"
        >
          Documento de origen
        </h2>
        <dl className="mt-3 grid gap-px border border-concrete-200 bg-concrete-200 text-sm sm:grid-cols-2">
          <div className="bg-white px-4 py-3">
            <dt className="text-xs font-semibold text-ink-500">Orden de compra</dt>
            <dd className="mt-1 font-semibold tabular-nums">
              {order?.code ??
                (bill.purchase_order_id === null
                  ? "—"
                  : `OC #${bill.purchase_order_id}`)}
            </dd>
          </div>
          <div className="bg-white px-4 py-3">
            <dt className="text-xs font-semibold text-ink-500">Recepción vinculada</dt>
            <dd className="mt-1 font-semibold tabular-nums">
              {receipt?.code ??
                (bill.goods_receipt_id === null
                  ? "Acumulado de la OC"
                  : `Recepción #${bill.goods_receipt_id}`)}
            </dd>
          </div>
          <div className="bg-white px-4 py-3">
            <dt className="text-xs font-semibold text-ink-500">Emisión</dt>
            <dd className="mt-1">{formatDate(bill.issue_date)}</dd>
          </div>
          <div className="bg-white px-4 py-3">
            <dt className="text-xs font-semibold text-ink-500">Vencimiento</dt>
            <dd className="mt-1">
              {formatDate(bill.due_date)}
              {isOverdue ? (
                <span className="ml-2 text-xs font-semibold text-signal-600">
                  Vencida
                </span>
              ) : null}
            </dd>
          </div>
        </dl>
        <p className="mt-2 border-l-2 border-concrete-200 bg-concrete-50 px-3 py-2 text-xs text-ink-500">
          Las facturas son inmutables: no se editan ni se eliminan. Las
          correcciones se hacen con abonos, anulación o documentos de
          contrapartida.
        </p>
      </section>

      <section className="mt-8" aria-labelledby="bill-payments-heading">
        <div className="flex items-end justify-between gap-3">
          <div>
            <h2
              id="bill-payments-heading"
              className="text-sm font-bold tracking-tight"
            >
              Historial de abonos
            </h2>
            <p className="mt-0.5 text-xs text-ink-500">
              Cada abono queda registrado con fecha, referencia e importe.
            </p>
          </div>
          {canPay ? (
            <button
              type="button"
              onClick={() => setPaymentOpen(true)}
              className="shrink-0 border border-concrete-200 px-3 py-1.5 text-xs font-semibold text-ink-700 hover:border-ink-950 hover:text-ink-950"
            >
              Nuevo abono
            </button>
          ) : null}
        </div>
        <div className="mt-3">
          <PaymentsTable
            payments={paymentsQuery.data ?? []}
            isPending={paymentsQuery.isPending}
          />
        </div>
        {paymentsQuery.error === null ? null : (
          <p className="mt-2 border-l-2 border-signal-500 bg-signal-100 px-3 py-2 text-xs font-medium text-signal-600">
            No se pudo cargar el historial: {paymentsQuery.error.message}
          </p>
        )}
      </section>

      <BillPaymentForm
        open={paymentOpen}
        bill={bill}
        onClose={() => setPaymentOpen(false)}
        onDone={handlePaymentDone}
      />

      <PurchasingDialog
        open={voidOpen}
        title={`Anular factura ${bill.code}`}
        subtitle="La anulación conserva el documento y su historial, y libera el saldo facturable de la orden."
        onClose={() => setVoidOpen(false)}
        footer={
          <>
            <button
              type="button"
              onClick={() => setVoidOpen(false)}
              className="border border-concrete-200 px-4 py-2 text-sm font-semibold text-ink-700 hover:border-ink-500 hover:text-ink-950"
            >
              Volver
            </button>
            <button
              type="button"
              onClick={() => handleVoid(bill.id)}
              disabled={voidMutation.isPending}
              className="bg-signal-500 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-signal-600 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {voidMutation.isPending ? "Anulando…" : "Confirmar anulación"}
            </button>
          </>
        }
      >
        <p className="text-sm text-ink-700">
          Solo se pueden anular facturas <strong>PENDING</strong> sin abonos. Esta
          factura tiene un total de {formatMoney(bill.total)} y un saldo de{" "}
          {formatMoney(bill.balance_due)}.
        </p>
        <p className="border-l-2 border-clay-600 bg-clay-100 px-3 py-2 text-xs font-medium text-clay-600">
          {BILL_STATUS_LABELS[bill.status]} · {BILL_STATUS_HINTS[bill.status]}
        </p>
        {mutationMessage === null ? null : (
          <div
            role="alert"
            className="border-l-2 border-signal-500 bg-signal-100 px-3 py-2 text-sm font-medium text-signal-600"
          >
            <p>{mutationMessage}</p>
            <p className="mt-1 font-normal">
              {errorHint(mutationMessage) ??
                "Revisa el estado de la factura y vuelve a intentarlo."}
            </p>
          </div>
        )}
      </PurchasingDialog>
    </div>
  );
}
