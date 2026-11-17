import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import {
  useCreateCustomer,
  useUpdateCustomer,
} from "../../api/sales";
import type { Customer, CustomerCreate, CustomerUpdate } from "../../api/sales";
import ActiveSwitch from "../../components/ActiveSwitch";
import FormSheet from "../../components/FormSheet";
import { moneyString, parseAmount } from "./format";

interface CustomerFormProps {
  open: boolean;
  /** `null` para crear; un cliente para editar. */
  customer: Customer | null;
  onClose: () => void;
  onSaved: (customer: Customer, mode: "created" | "updated") => void;
}

const labelClass = "mb-1.5 block text-xs font-semibold text-ink-700";
const fieldClass =
  "w-full border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-950 " +
  "placeholder:text-concrete-400 focus:border-ink-950";
const hintClass = "mt-1 text-xs text-ink-500";

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function CustomerForm({
  open,
  customer,
  onClose,
  onSaved,
}: CustomerFormProps) {
  const isEdit = customer !== null;

  const [taxId, setTaxId] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [contactName, setContactName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [address, setAddress] = useState("");
  const [creditLimit, setCreditLimit] = useState("0.00");
  const [isActive, setIsActive] = useState(true);
  const [formError, setFormError] = useState<string | null>(null);

  const createMutation = useCreateCustomer();
  const updateMutation = useUpdateCustomer();
  const isPending = createMutation.isPending || updateMutation.isPending;
  const mutationError = createMutation.error ?? updateMutation.error;

  useEffect(() => {
    if (!open) {
      return;
    }
    setTaxId(customer?.tax_id ?? "");
    setCompanyName(customer?.company_name ?? "");
    setContactName(customer?.contact_name ?? "");
    setEmail(customer?.email ?? "");
    setPhone(customer?.phone ?? "");
    setAddress(customer?.address ?? "");
    setCreditLimit(
      customer === null ? "0.00" : String(customer.credit_limit),
    );
    setIsActive(customer === null ? true : customer.is_active);
    setFormError(null);
    createMutation.reset();
    updateMutation.reset();
    // `reset` es estable en TanStack Query; se omite de las dependencias.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, customer]);

  function validate(): string | null {
    if (taxId.trim() === "") {
      return "El NIT o identificador fiscal es obligatorio.";
    }
    if (taxId.trim().length > 50) {
      return "El identificador fiscal no puede superar 50 caracteres.";
    }
    if (companyName.trim() === "") {
      return "La razón social es obligatoria.";
    }
    if (companyName.trim().length > 200) {
      return "La razón social no puede superar 200 caracteres.";
    }
    if (contactName.trim() === "") {
      return "El nombre de contacto es obligatorio.";
    }
    if (contactName.trim().length > 150) {
      return "El nombre de contacto no puede superar 150 caracteres.";
    }
    if (!EMAIL_PATTERN.test(email.trim())) {
      return "Indica un correo de facturación válido.";
    }
    if (email.trim().length > 255) {
      return "El correo no puede superar 255 caracteres.";
    }
    if (phone.trim().length > 50) {
      return "El teléfono no puede superar 50 caracteres.";
    }
    if (address.trim() === "") {
      return "La dirección es obligatoria.";
    }
    if (address.trim().length > 255) {
      return "La dirección no puede superar 255 caracteres.";
    }
    const limit = parseAmount(creditLimit);
    if (creditLimit.trim() === "") {
      return "El límite de crédito es obligatorio (usa 0 si no otorgas cupo).";
    }
    if (limit === null) {
      return "Usa un límite mayor o igual a cero con hasta 2 decimales (ej. 5000.00).";
    }
    return null;
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = validate();
    if (message !== null) {
      setFormError(message);
      return;
    }
    setFormError(null);

    const limit = parseAmount(creditLimit);
    if (limit === null) {
      return;
    }
    const trimmedPhone = phone.trim();
    const payload = {
      tax_id: taxId.trim(),
      company_name: companyName.trim(),
      contact_name: contactName.trim(),
      email: email.trim(),
      phone: trimmedPhone === "" ? null : trimmedPhone,
      address: address.trim(),
      credit_limit: moneyString(limit),
      is_active: isActive,
    } satisfies CustomerCreate;

    if (customer === null) {
      createMutation.mutate(payload, {
        onSuccess: (created) => onSaved(created, "created"),
      });
      return;
    }
    updateMutation.mutate(
      {
        customerId: customer.id,
        payload: payload satisfies CustomerUpdate,
      },
      { onSuccess: (updated) => onSaved(updated, "updated") },
    );
  }

  const serverError =
    mutationError instanceof Error ? mutationError.message : null;
  const visibleError = formError ?? serverError;

  return (
    <FormSheet
      open={open}
      title={isEdit ? "Editar cliente" : "Nuevo cliente"}
      subtitle={
        isEdit
          ? `Actualiza los datos comerciales de ${customer.company_name}.`
          : "Registra la cuenta comercial con la que se emitirán pedidos y facturas."
      }
      submitLabel={isEdit ? "Guardar cambios" : "Crear cliente"}
      pendingLabel="Guardando…"
      isPending={isPending}
      onClose={onClose}
      onSubmit={handleSubmit}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className={labelClass} htmlFor="customer-tax-id">
            NIT / Identificador fiscal{" "}
            <span className="text-signal-600">*</span>
          </label>
          <input
            id="customer-tax-id"
            // eslint-disable-next-line jsx-a11y/no-autofocus
            autoFocus={!isEdit}
            className={fieldClass}
            type="text"
            maxLength={50}
            value={taxId}
            onChange={(event) => setTaxId(event.currentTarget.value)}
            placeholder="900123456-1"
          />
          <p className={hintClass}>Único en todo el ERP.</p>
        </div>
        <div>
          <label className={labelClass} htmlFor="customer-company">
            Razón social <span className="text-signal-600">*</span>
          </label>
          <input
            id="customer-company"
            className={fieldClass}
            type="text"
            maxLength={200}
            value={companyName}
            onChange={(event) => setCompanyName(event.currentTarget.value)}
            placeholder="Aceros del Norte S.A.S."
          />
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className={labelClass} htmlFor="customer-contact">
            Contacto <span className="text-signal-600">*</span>
          </label>
          <input
            id="customer-contact"
            className={fieldClass}
            type="text"
            maxLength={150}
            value={contactName}
            onChange={(event) => setContactName(event.currentTarget.value)}
            placeholder="María Gómez"
          />
        </div>
        <div>
          <label className={labelClass} htmlFor="customer-phone">
            Teléfono <span className="font-normal text-ink-500">(opcional)</span>
          </label>
          <input
            id="customer-phone"
            className={fieldClass}
            type="tel"
            maxLength={50}
            value={phone}
            onChange={(event) => setPhone(event.currentTarget.value)}
            placeholder="+57 601 555 0100"
          />
        </div>
      </div>

      <div>
        <label className={labelClass} htmlFor="customer-email">
          Correo de facturación <span className="text-signal-600">*</span>
        </label>
        <input
          id="customer-email"
          className={fieldClass}
          type="email"
          maxLength={255}
          value={email}
          onChange={(event) => setEmail(event.currentTarget.value)}
          placeholder="facturacion@acerosnorte.com"
        />
      </div>

      <div>
        <label className={labelClass} htmlFor="customer-address">
          Dirección <span className="text-signal-600">*</span>
        </label>
        <input
          id="customer-address"
          className={fieldClass}
          type="text"
          maxLength={255}
          value={address}
          onChange={(event) => setAddress(event.currentTarget.value)}
          placeholder="Calle 1 # 2-3, Bogotá"
        />
      </div>

      <div>
        <label className={labelClass} htmlFor="customer-credit">
          Límite de crédito <span className="text-signal-600">*</span>
        </label>
        <input
          id="customer-credit"
          className={fieldClass}
          type="text"
          inputMode="decimal"
          value={creditLimit}
          onChange={(event) => setCreditLimit(event.currentTarget.value)}
          placeholder="5000.00"
        />
        <p className={hintClass}>
          Cupo máximo de deuda vigente. Usa 0 para operar solo de contado.
        </p>
      </div>

      <ActiveSwitch
        checked={isActive}
        onChange={setIsActive}
        label="Cliente activo"
        hint="Un cliente inactivo no puede recibir pedidos ni facturas nuevas."
      />

      {visibleError === null ? null : (
        <p
          role="alert"
          className="border-l-2 border-signal-500 bg-signal-100 px-3 py-2 text-sm font-medium text-signal-600"
        >
          {visibleError}
        </p>
      )}
    </FormSheet>
  );
}
