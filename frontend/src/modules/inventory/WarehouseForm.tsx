import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { useCreateWarehouse } from "../../api/inventory";
import type { Warehouse, WarehouseCreate } from "../../api/inventory";
import ActiveSwitch from "../../components/ActiveSwitch";
import FormSheet from "../../components/FormSheet";

interface WarehouseFormProps {
  open: boolean;
  onClose: () => void;
  onSaved: (warehouse: Warehouse) => void;
}

const labelClass = "mb-1.5 block text-xs font-semibold text-ink-700";
const fieldClass =
  "w-full border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-950 " +
  "placeholder:text-concrete-400 focus:border-ink-950";
const hintClass = "mt-1 text-xs text-ink-500";

/**
 * Alta de bodegas.
 *
 * La API expone solo `POST` y `GET` para almacenes (spec §4.2), así que este
 * formulario cubre únicamente la creación.
 */
export default function WarehouseForm({
  open,
  onClose,
  onSaved,
}: WarehouseFormProps) {
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [formError, setFormError] = useState<string | null>(null);

  const createMutation = useCreateWarehouse();
  const isPending = createMutation.isPending;

  useEffect(() => {
    if (!open) {
      return;
    }
    setCode("");
    setName("");
    setAddress("");
    setIsActive(true);
    setFormError(null);
    createMutation.reset();
    // `reset` es estable en TanStack Query; se omite de las dependencias.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  function validate(): string | null {
    if (code.trim() === "") {
      return "El código de la bodega es obligatorio.";
    }
    if (code.trim().length > 50) {
      return "El código no puede superar 50 caracteres.";
    }
    if (name.trim() === "") {
      return "El nombre de la bodega es obligatorio.";
    }
    if (name.trim().length > 150) {
      return "El nombre no puede superar 150 caracteres.";
    }
    if (address.trim().length > 255) {
      return "La dirección no puede superar 255 caracteres.";
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

    const trimmedAddress = address.trim();
    const payload: WarehouseCreate = {
      code: code.trim(),
      name: name.trim(),
      address: trimmedAddress === "" ? null : trimmedAddress,
      is_active: isActive,
    };

    createMutation.mutate(payload, {
      onSuccess: (warehouse) => onSaved(warehouse),
    });
  }

  const serverError =
    createMutation.error instanceof Error ? createMutation.error.message : null;
  const visibleError = formError ?? serverError;

  return (
    <FormSheet
      open={open}
      title="Nueva bodega"
      subtitle="Registra un almacén físico o lógico para el inventario."
      submitLabel="Crear bodega"
      pendingLabel="Guardando…"
      isPending={isPending}
      onClose={onClose}
      onSubmit={handleSubmit}
    >
      <div>
        <label className={labelClass} htmlFor="warehouse-code">
          Código <span className="text-signal-600">*</span>
        </label>
        <input
          id="warehouse-code"
          // eslint-disable-next-line jsx-a11y/no-autofocus
          autoFocus
          className={fieldClass}
          type="text"
          maxLength={50}
          value={code}
          onChange={(event) => setCode(event.currentTarget.value)}
          placeholder="BOD-MED-01"
        />
        <p className={hintClass}>Único en todo el ERP (máx. 50 caracteres).</p>
      </div>

      <div>
        <label className={labelClass} htmlFor="warehouse-name">
          Nombre <span className="text-signal-600">*</span>
        </label>
        <input
          id="warehouse-name"
          className={fieldClass}
          type="text"
          maxLength={150}
          value={name}
          onChange={(event) => setName(event.currentTarget.value)}
          placeholder="Bodega Principal Medellín"
        />
      </div>

      <div>
        <label className={labelClass} htmlFor="warehouse-address">
          Dirección <span className="font-normal text-ink-500">(opcional)</span>
        </label>
        <input
          id="warehouse-address"
          className={fieldClass}
          type="text"
          maxLength={255}
          value={address}
          onChange={(event) => setAddress(event.currentTarget.value)}
          placeholder="Calle 1 #2-3, Medellín"
        />
      </div>

      <ActiveSwitch
        checked={isActive}
        onChange={setIsActive}
        label="Bodega activa"
        hint="Solo las bodegas activas aparecen en los selectores de movimientos."
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
