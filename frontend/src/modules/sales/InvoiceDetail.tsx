import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  useCreditNotes,
  useCustomers,
  useInvoice,
  useInvoicePayments,
} from "../../api/sales";
import type { InvoicePayment } from "../../api/sales";
import { canWriteModule, useAuth } from "../../store/authStore";
import CreditNoteForm from "./CreditNoteForm";
import { INVOICE_STATUS_HINTS, INVOICE_STATUS_LABELS } from "./constants";
import { formatDate, formatMoney, todayIso } from "./format";
import PaymentForm from "./PaymentForm";
import SalesTabs from "./SalesTabs";
import { InvoiceStatusBadge } from "./SalesStatusBadge";

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
  hint?: string;
  emphasis?: boolean;
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
  payments: InvoicePayment[];
  isPending: boolean;
}) {
  if (isPending) {
    return (
      <p className="border border-concrete-200 bg-white px-4 py-6 text-sm text-ink-500">
        Cargando historial de pagos…
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
              Registrado
            </th>
            <th scope="col" className="px-4 py-2.5 text-right">
              Importe
            </th>
          </tr>
        </thead>
        <tbody>
          {payments.map((payment) => (
            <tr
              key={payment.id}
              className="border-b border-concrete-100 last:border-b-0"
            >
              <td className="px-4 py-2.5 text-xs text-ink-700">
                {formatDate(payment.paid_at)}
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

interface InvoiceDetailContentProps {
  invoiceId: number;
}

function InvoiceDetailContent({ invoiceId }: InvoiceDetailContentProps) {
  const { user } = useAuth();
  const invoiceQuery = useInvoice(invoiceId);
  const paymentsQuery = useInvoicePayments(invoiceId);
  const notesQuery = useCreditNotes(invoiceId);
  const customersQuery = useCustomers({ limit: 200 });

  const [paymentOpen, setPaymentOpen] = useState(false);
  const [noteOpen, setNoteOpen] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  const canWrite = canWriteModule(user, "sales");

  if (invoiceQuery.error !== null) {
    return (
      <div className="mx-auto w-full max-w-[1200px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
        <div className="border border-signal-500/40 bg-signal-100 px-5 py-6">
          <p className="text-sm font-semibold text-signal-600">
            No se pudo cargar la factura.
          </p>
          <p className="mt-1 text-sm text-ink-700">
            {invoiceQuery.error.message}
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void invoiceQuery.refetch()}
              className="border border-signal-500 px-3 py-1.5 text-sm font-semibold text-signal-600 hover:bg-signal-500 hover:text-white"
            >
              Reintentar
            </button>
            <Link
              to="/sales/invoices"
              className="border border-concrete-200 px-3 py-1.5 text-sm font-semibold text-ink-700 hover:border-ink-950 hover:text-ink-950"
            >
              Volver a facturas
            </Link>
          </div>
        </div>
      </div>
    );
  }

  const invoice = invoiceQuery.data;

  if (invoice === undefined) {
    return (
      <div className="mx-auto w-full max-w-[1200px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
        <div className="h-10 w-64 animate-pulse bg-concrete-100" />
        <div className="mt-6 h-28 animate-pulse border border-concrete-200 bg-white" />
        <div className="mt-5 h-48 animate-pulse border border-concrete-200 bg-white" />
      </div>
    );
  }

  const customer = (customersQuery.data ?? []).find(
    (item) => item.id === invoice.customer_id,
  );
  const payments = paymentsQuery.data ?? [];
  const notes = notesQuery.data ?? [];

  const totalCents = Math.round(Number(invoice.total) * 100);
  const balanceCents = Math.round(Number(invoice.balance_due) * 100);
  const creditedCents = notes.reduce(
    (total, note) => total + Math.round(Number(note.amount) * 100),
    0,
  );
  const paidCents =
    invoice.status === "VOID"
      ? 0
      : Math.max(0, totalCents - balanceCents - creditedCents);
  const creditableCents = Math.max(0, totalCents - creditedCents);

  const isOverdue =
    invoice.status === "ISSUED" && invoice.due_date < todayIso();
  const canPay = invoice.status === "ISSUED" && balanceCents > 0;
  const canCredit = invoice.status !== "VOID" && creditableCents > 0;

  const visibleNotes = [...notes].reverse();
  const visiblePayments = [...payments].reverse();

  function handleDone(message: string) {
    setFeedback({ tone: "success", text: message });
    setPaymentOpen(false);
    setNoteOpen(false);
  }

  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
      <Link
        to="/sales/invoices"
        className="text-xs font-semibold text-ink-500 underline-offset-2 hover:text-ink-950 hover:underline"
      >
        ← Volver a facturas
      </Link>

      <header className="mt-4 flex flex-col gap-5 border-b-2 border-ink-950 pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-signal-600">
              Factura de venta
            </p>
            <InvoiceStatusBadge status={invoice.status} />
          </div>
          <h1 className="mt-2 text-4xl font-extrabold tracking-tight tabular-nums sm:text-5xl">
            {invoice.code}
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-700">
            {customer?.company_name ?? `Cliente #${invoice.customer_id}`} ·{" "}
            {INVOICE_STATUS_HINTS[invoice.status]}
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          {canWrite && canPay ? (
            <button
              type="button"
              onClick={() => setPaymentOpen(true)}
              className="bg-signal-500 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-signal-600"
            >
              Registrar abono
            </button>
          ) : null}
          {canWrite && canCredit ? (
            <button
              type="button"
              onClick={() => setNoteOpen(true)}
              className="border border-ink-950 px-4 py-2.5 text-sm font-semibold text-ink-950 transition-colors hover:bg-ink-950 hover:text-concrete-50"
            >
              Emitir nota crédito
            </button>
          ) : null}
        </div>
      </header>

      <SalesTabs />

      {feedback === null ? null : (
        <div
          role={feedback.tone === "error" ? "alert" : "status"}
          className={[
            "mt-5 flex items-start justify-between gap-4 border px-4 py-3 text-sm font-medium",
            feedback.tone === "success"
              ? "border-pine-600/30 bg-pine-100 text-pine-600"
              : "border-signal-500/40 bg-signal-100 text-signal-600",
          ].join(" ")}
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

      {canWrite ? null : (
        <p className="mt-5 border-l-2 border-concrete-400 bg-white px-4 py-3 text-sm text-ink-700">
          Tu perfil tiene acceso de lectura al módulo de ventas. Los abonos y las
          notas crédito requieren escritura.
        </p>
      )}

      <dl className="mt-6 grid grid-cols-2 gap-px border border-concrete-200 bg-concrete-200 lg:grid-cols-4">
        <SummaryCard label="Total facturado" value={formatMoney(invoice.total)} />
        <SummaryCard
          label="Abonos aplicados"
          value={formatMoney(paidCents / 100)}
          hint={`${payments.length} pago${payments.length === 1 ? "" : "s"}`}
        />
        <SummaryCard
          label="Notas crédito"
          value={formatMoney(creditedCents / 100)}
          hint={`${notes.length} nota${notes.length === 1 ? "" : "s"}`}
        />
        <SummaryCard
          label="Saldo pendiente"
          value={formatMoney(invoice.balance_due)}
          hint={
            invoice.status === "VOID"
              ? "Factura anulada"
              : isOverdue
                ? "Vencida y pendiente de cobro"
                : INVOICE_STATUS_LABELS[invoice.status]
          }
          emphasis={canPay}
        />
      </dl>

      <div className="mt-6 grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <section
          aria-labelledby="invoice-data-title"
          className="border border-concrete-200 bg-white p-5"
        >
          <h2
            id="invoice-data-title"
            className="text-xs font-semibold uppercase tracking-[0.16em] text-ink-500"
          >
            Datos del documento
          </h2>
          <dl className="mt-4 space-y-3 text-sm">
            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-ink-500">Emisión</dt>
              <dd className="font-medium tabular-nums">
                {formatDate(invoice.issue_date)}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-ink-500">Límite de pago</dt>
              <dd
                className={
                  isOverdue
                    ? "font-semibold tabular-nums text-clay-600"
                    : "font-medium tabular-nums"
                }
              >
                {formatDate(invoice.due_date)}
                {isOverdue ? " · vencida" : ""}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-ink-500">Origen</dt>
              <dd className="font-medium">
                {invoice.sales_order_id === null ? (
                  "Venta directa"
                ) : (
                  <Link
                    to="/sales/orders"
                    className="tabular-nums underline-offset-2 hover:underline"
                  >
                    Pedido #{invoice.sales_order_id}
                  </Link>
                )}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-ink-500">Importe acreditable</dt>
              <dd className="font-medium tabular-nums">
                {formatMoney(creditableCents / 100)}
              </dd>
            </div>
          </dl>
        </section>

        <section
          aria-labelledby="invoice-customer-title"
          className="border border-concrete-200 bg-white p-5"
        >
          <h2
            id="invoice-customer-title"
            className="text-xs font-semibold uppercase tracking-[0.16em] text-ink-500"
          >
            Cliente
          </h2>
          <dl className="mt-4 space-y-3 text-sm">
            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-ink-500">Razón social</dt>
              <dd className="max-w-[60%] text-right font-medium">
                {customer?.company_name ?? `Cliente #${invoice.customer_id}`}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-ink-500">NIT</dt>
              <dd className="font-medium tabular-nums">
                {customer?.tax_id ?? "—"}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-ink-500">Correo</dt>
              <dd className="max-w-[60%] truncate text-right font-medium">
                {customer?.email ?? "—"}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-ink-500">Dirección</dt>
              <dd className="max-w-[60%] text-right font-medium">
                {customer?.address ?? "—"}
              </dd>
            </div>
          </dl>
        </section>
      </div>

      {!canPay && invoice.status !== "ISSUED" ? (
        <p className="mt-5 border-l-2 border-concrete-400 bg-white px-4 py-3 text-sm text-ink-700">
          {invoice.status === "PAID"
            ? "La factura está pagada. Para devolver importes emite una nota crédito."
            : "La factura está anulada y no admite pagos ni notas crédito."}
        </p>
      ) : null}

      <section aria-labelledby="invoice-payments-title" className="mt-8">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2
              id="invoice-payments-title"
              className="text-lg font-bold tracking-tight"
            >
              Historial de pagos
            </h2>
            <p className="mt-0.5 text-xs text-ink-500">
              Abonos registrados sobre la factura, del más reciente al más
              antiguo.
            </p>
          </div>
          {paymentsQuery.isFetching ? (
            <span className="text-xs text-ink-500" aria-live="polite">
              actualizando…
            </span>
          ) : null}
        </div>

        <div className="mt-3">
          {paymentsQuery.error !== null ? (
            <div className="border border-signal-500/40 bg-signal-100 px-4 py-4 text-sm">
              <p className="font-semibold text-signal-600">
                No se pudo cargar el historial de pagos.
              </p>
              <p className="mt-1 text-ink-700">{paymentsQuery.error.message}</p>
              <button
                type="button"
                onClick={() => void paymentsQuery.refetch()}
                className="mt-3 border border-signal-500 px-3 py-1.5 text-xs font-semibold text-signal-600 hover:bg-signal-500 hover:text-white"
              >
                Reintentar
              </button>
            </div>
          ) : (
            <PaymentsTable
              payments={visiblePayments}
              isPending={paymentsQuery.isPending}
            />
          )}
        </div>
      </section>

      <section aria-labelledby="invoice-notes-title" className="mt-8">
        <div>
          <h2
            id="invoice-notes-title"
            className="text-lg font-bold tracking-tight"
          >
            Notas crédito
          </h2>
          <p className="mt-0.5 text-xs text-ink-500">
            Devoluciones y descuentos que reducen el saldo sin modificar la
            factura original.
          </p>
        </div>

        <div className="mt-3">
          {notesQuery.error !== null ? (
            <div className="border border-signal-500/40 bg-signal-100 px-4 py-4 text-sm">
              <p className="font-semibold text-signal-600">
                No se pudieron cargar las notas crédito.
              </p>
              <p className="mt-1 text-ink-700">{notesQuery.error.message}</p>
              <button
                type="button"
                onClick={() => void notesQuery.refetch()}
                className="mt-3 border border-signal-500 px-3 py-1.5 text-xs font-semibold text-signal-600 hover:bg-signal-500 hover:text-white"
              >
                Reintentar
              </button>
            </div>
          ) : notesQuery.isPending ? (
            <p className="border border-concrete-200 bg-white px-4 py-6 text-sm text-ink-500">
              Cargando notas crédito…
            </p>
          ) : visibleNotes.length === 0 ? (
            <p className="border border-dashed border-concrete-200 bg-white px-4 py-6 text-sm text-ink-500">
              No hay notas crédito emitidas sobre esta factura.
            </p>
          ) : (
            <div className="border border-concrete-200 bg-white">
              <table className="w-full border-collapse text-left text-sm">
                <thead>
                  <tr className="border-b border-concrete-200 text-xs font-semibold text-ink-500">
                    <th scope="col" className="px-4 py-2.5">
                      Nota
                    </th>
                    <th scope="col" className="px-4 py-2.5">
                      Emisión
                    </th>
                    <th scope="col" className="px-4 py-2.5">
                      Motivo
                    </th>
                    <th scope="col" className="px-4 py-2.5 text-right">
                      Importe
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {visibleNotes.map((note) => (
                    <tr
                      key={note.id}
                      className="border-b border-concrete-100 last:border-b-0"
                    >
                      <td className="px-4 py-2.5 font-semibold tabular-nums">
                        {note.code}
                      </td>
                      <td className="px-4 py-2.5 text-xs text-ink-700">
                        {formatDate(note.issue_date)}
                      </td>
                      <td className="max-w-[280px] px-4 py-2.5 text-xs text-ink-700">
                        <span className="line-clamp-2">
                          {note.reason ?? "—"}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-right font-semibold tabular-nums">
                        {formatMoney(note.amount)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>

      <PaymentForm
        open={paymentOpen}
        invoice={invoice}
        onClose={() => setPaymentOpen(false)}
        onDone={handleDone}
      />

      <CreditNoteForm
        open={noteOpen}
        invoice={invoice}
        credited={creditedCents / 100}
        onClose={() => setNoteOpen(false)}
        onDone={handleDone}
      />
    </div>
  );
}

/** Detalle de factura con historial de pagos y notas crédito. */
export default function InvoiceDetail() {
  const { invoiceId } = useParams<{ invoiceId: string }>();
  const parsed = invoiceId === undefined ? Number.NaN : Number(invoiceId);

  if (!Number.isInteger(parsed) || parsed <= 0) {
    return (
      <div className="mx-auto w-full max-w-[1200px] px-4 pb-16 pt-10 sm:px-6 lg:px-10">
        <div className="border border-dashed border-concrete-200 bg-white px-6 py-16 text-center">
          <p className="text-lg font-semibold">Identificador de factura inválido.</p>
          <p className="mt-2 text-sm text-ink-500">
            La dirección no corresponde a ninguna factura del sistema.
          </p>
          <Link
            to="/sales/invoices"
            className="mt-5 inline-block border border-ink-950 px-4 py-2 text-sm font-semibold hover:bg-ink-950 hover:text-concrete-50"
          >
            Volver a facturas
          </Link>
        </div>
      </div>
    );
  }

  return <InvoiceDetailContent invoiceId={parsed} />;
}
