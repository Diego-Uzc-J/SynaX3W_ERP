import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import {
  useCreateSupplier,
  useUpdateSupplier,
} from "../../api/purchasing";
import type {
  Supplier,
  SupplierCreate,
  SupplierUpdate,
} from "../../api/purchasing";
import ActiveSwitch from "../../components/ActiveSwitch";
import FormSheet from "../../components/FormSheet";
import { errorHint, errorMessage } from "./errors";

interface SupplierFormProps {
  open: boolean;
  /** `null` para crear; un proveedor para editar. */
  supplier: Supplier | null;
  onClose: () => void;
  onSaved: (supplier: Supplier, mode: "created" | "updated") => void;
}

const labelClass = "mb-1.5 block text-xs font-semibold text-ink-700";
const fieldClass =
  "w-full border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-950 " +
  "placeholder:text-concrete-400 focus:border-ink-950";
const hintClass = "mt-1 text-xs text-ink-500";

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const PHONE_PATTERN = /^[0-9+()\s-]{7,50}$/;

export default function SupplierForm({
  open,
  supplier,
  onClose,
  onSaved,
}: SupplierFormProps) {
  const isEdit = supplier !== null;

  const [taxId, setTaxId] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [contactName, setContactName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [address, setAddress] = useState("");
  const [paymentTerms, setPaymentTerms] = useState("30");
  const [isActive, setIsActive] = useState(true);
  const [formError, setFormError] = useState<string | null>(null);

  const createMutation = useCreateSupplier();
  const updateMutation = useUpdateSupplier();
  const isPending = createMutation.isPending || updateMutation.isPending;
  const mutationError = createMutation.error ?? updateMutation.error;

  useEffect(() => {
    if (!open) {
      return;
    }
    setTaxId(supplier?.tax_id ?? "");
    setCompanyName(supplier?.company_name ?? "");
    setContactName(supplier?.contact_name ?? "");
    setEmail(supplier?.email ?? "");
    setPhone(supplier?.phone ?? "");
    setAddress(supplier?.address ?? "");
    setPaymentTerms(
      supplier === null ? "30" : String(supplier.payment_terms_days),
    );
    setIsActive(supplier === null ? true : supplier.is_active);
    setFormError(null);
    createMutation.reset();
    updateMutation.reset();
    // `reset` es estable en TanStack Query; se omite de las dependencias.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, supplier]);

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
      return "Indica un correo de contacto válido.";
    }
    if (email.trim().length > 255) {
      return "El correo no puede superar 255 caracteres.";
    }
    if (phone.trim() !== "" && !PHONE_PATTERN.test(phone.trim())) {
      return "El teléfono debe tener entre 7 y 50 caracteres válidos.";
    }
    if (address.trim() === "") {
      return "La dirección es obligatoria.";
    }
    if (address.trim().length > 255) {
      return "La dirección no puede superar 255 caracteres.";
    }
    if (!/^\d{1,5}$/.test(paymentTerms.trim())) {
      return "Los plazos de pago deben ser un número entero mayor o igual a cero.";
    }
    if (Number(paymentTerms.trim()) > 3650) {
      return "Los plazos de pago no pueden superar 3650 días.";
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

    const trimmedPhone = phone.trim();
    const payload: SupplierCreate = {
      tax_id: taxId.trim(),
      company_name: companyName.trim(),
      contact_name: contactName.trim(),
      email: email.trim(),
      phone: trimmedPhone === "" ? null : trimmedPhone,
      address: address.trim(),
      payment_terms_days: Number(paymentTerms.trim()),
      is_active: isActive,
    };

    if (supplier === null) {
      createMutation.mutate(payload, {
        onSuccess: (created) => onSaved(created, "created"),
      });
      return;
    }
    updateMutation.mutate(
      {
        supplierId: supplier.id,
        payload: payload satisfies SupplierUpdate,
      },
      { onSuccess: (updated) => onSaved(updated, "updated") },
    );
  }

  const serverMessage = errorMessage(mutationError);
  const serverHint = serverMessage === null ? null : errorHint(serverMessage);
  const visibleError = formError ?? serverMessage;

  return (
    <FormSheet
      open={open}
      title={isEdit ? "Editar proveedor" : "Nuevo proveedor"}
      subtitle={
        isEdit
          ? `Actualiza los datos y las condiciones de pago de ${supplier.company_name}.`
          : "Registra el tercero al que se emitirán órdenes de compra. El NIT es único."
      }
      submitLabel={isEdit ? "Guardar cambios" : "Crear proveedor"}
      pendingLabel="Guardando…"
      isPending={isPending}
      onClose={onClose}
      onSubmit={handleSubmit}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className={labelClass} htmlFor="supplier-tax-id">
            NIT / Identificador fiscal{" "}
            <span className="text-signal-600">*</span>
          </label>
          <input
            id="supplier-tax-id"
            // eslint-disable-next-line jsx-a11y/no-autofocus
            autoFocus={!isEdit}
            className={fieldClass}
            type="text"
            maxLength={50}
            value={taxId}
            onChange={(event) => setTaxId(event.currentTarget.value)}
            placeholder="800987654-3"
          />
          <p className={hintClass}>Único en todo el ERP.</p>
        </div>
        <div>
          <label className={labelClass} htmlFor="supplier-company">
            Razón social <span className="text-signal-600">*</span>
          </label>
          <input
            id="supplier-company"
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
          <label className={labelClass} htmlFor="supplier-contact">
            Contacto <span className="text-signal-600">*</span>
          </label>
          <input
            id="supplier-contact"
            className={fieldClass}
            type="text"
            maxLength={150}
            value={contactName}
            onChange={(event) => setContactName(event.currentTarget.value)}
            placeholder="María Gómez"
          />
        </div>
        <div>
          <label className={labelClass} htmlFor="supplier-phone">
            Teléfono{" "}
            <span className="font-normal text-ink-500">(opcional)</span>
          </label>
          <input
            id="supplier-phone"
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
        <label className={labelClass} htmlFor="supplier-email">
          Correo de contacto <span className="text-signal-600">*</span>
        </label>
        <input
          id="supplier-email"
          className={fieldClass}
          type="email"
          maxLength={255}
          value={email}
          onChange={(event) => setEmail(event.currentTarget.value)}
          placeholder="ventas@acerosnorte.com"
        />
        <p className={hintClass}>Se usa para el envío de órdenes de compra.</p>
      </div>

      <div>
        <label className={labelClass} htmlFor="supplier-address">
          Dirección <span className="text-signal-600">*</span>
        </label>
        <input
          id="supplier-address"
          className={fieldClass}
          type="text"
          maxLength={255}
          value={address}
          onChange={(event) => setAddress(event.currentTarget.value)}
          placeholder="Calle 1 # 2-3, Bogotá"
        />
      </div>

      <div>
        <label className={labelClass} htmlFor="supplier-terms">
          Plazos de pago (días) <span className="text-signal-600">*</span>
        </label>
        <input
          id="supplier-terms"
          className={fieldClass}
          type="text"
          inputMode="numeric"
          value={paymentTerms}
          onChange={(event) => setPaymentTerms(event.currentTarget.value)}
          placeholder="30"
        />
        <p className={hintClass}>
          Se usan para calcular la fecha de vencimiento de las facturas.
        </p>
      </div>

      <ActiveSwitch
        checked={isActive}
        onChange={setIsActive}
        label="Proveedor activo"
        hint="Un proveedor inactivo no puede recibir nuevas órdenes ni recepciones."
      />

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
