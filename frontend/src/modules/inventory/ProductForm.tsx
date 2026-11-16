import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import { useCreateProduct, useUpdateProduct } from "../../api/inventory";
import type { Product, ProductCreate } from "../../api/inventory";
import ActiveSwitch from "../../components/ActiveSwitch";
import FormSheet from "../../components/FormSheet";

interface ProductFormProps {
  open: boolean;
  /** `null` para crear; un producto para editar. */
  product: Product | null;
  onClose: () => void;
  onSaved: (product: Product, mode: "created" | "updated") => void;
}

const labelClass = "mb-1.5 block text-xs font-semibold text-ink-700";
const fieldClass =
  "w-full border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-950 " +
  "placeholder:text-concrete-400 focus:border-ink-950";
const hintClass = "mt-1 text-xs text-ink-500";

/** Acepta coma decimal y separadores de miles, y normaliza al punto de la API. */
function normalizePrice(value: string): string {
  const trimmed = value.trim();
  if (!trimmed.includes(",")) {
    return trimmed;
  }
  return trimmed.replace(/\./g, "").replace(",", ".");
}

export default function ProductForm({
  open,
  product,
  onClose,
  onSaved,
}: ProductFormProps) {
  const isEdit = product !== null;

  const [sku, setSku] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [unitPrice, setUnitPrice] = useState("");
  const [minimumStock, setMinimumStock] = useState("5");
  const [isActive, setIsActive] = useState(true);
  const [formError, setFormError] = useState<string | null>(null);

  const createMutation = useCreateProduct();
  const updateMutation = useUpdateProduct();
  const isPending = createMutation.isPending || updateMutation.isPending;
  const mutationError = createMutation.error ?? updateMutation.error;

  useEffect(() => {
    if (!open) {
      return;
    }
    setSku(product?.sku ?? "");
    setName(product?.name ?? "");
    setDescription(product?.description ?? "");
    setUnitPrice(product === null ? "" : String(product.unit_price));
    setMinimumStock(product === null ? "5" : String(product.minimum_stock));
    setIsActive(product === null ? true : product.is_active);
    setFormError(null);
    createMutation.reset();
    updateMutation.reset();
    // `reset` es estable en TanStack Query; se omite de las dependencias.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, product]);

  function validate(): string | null {
    if (sku.trim() === "") {
      return "El SKU es obligatorio.";
    }
    if (sku.trim().length > 50) {
      return "El SKU no puede superar 50 caracteres.";
    }
    if (name.trim() === "") {
      return "El nombre es obligatorio.";
    }
    if (name.trim().length > 200) {
      return "El nombre no puede superar 200 caracteres.";
    }
    const price = normalizePrice(unitPrice);
    if (price === "") {
      return "El precio base es obligatorio.";
    }
    if (!/^\d{1,10}(\.\d{1,2})?$/.test(price)) {
      return "Usa un precio mayor o igual a cero con hasta 2 decimales (ej. 1899.90).";
    }
    const minimum = Number(minimumStock);
    if (minimumStock.trim() === "") {
      return "El stock mínimo es obligatorio (usa 0 si no aplica).";
    }
    if (!Number.isInteger(minimum) || minimum < 0) {
      return "El stock mínimo debe ser un entero mayor o igual a cero.";
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

    const trimmedDescription = description.trim();
    const payload: ProductCreate = {
      sku: sku.trim(),
      name: name.trim(),
      description: trimmedDescription === "" ? null : trimmedDescription,
      unit_price: normalizePrice(unitPrice),
      minimum_stock: Number(minimumStock),
      is_active: isActive,
    };

    if (product === null) {
      createMutation.mutate(payload, {
        onSuccess: (created) => onSaved(created, "created"),
      });
      return;
    }
    updateMutation.mutate(
      { productId: product.id, payload },
      { onSuccess: (updated) => onSaved(updated, "updated") },
    );
  }

  const serverError = mutationError instanceof Error ? mutationError.message : null;
  const visibleError = formError ?? serverError;

  return (
    <FormSheet
      open={open}
      title={isEdit ? "Editar producto" : "Nuevo producto"}
      subtitle={
        isEdit
          ? `Actualiza los datos del SKU ${product.sku}.`
          : "Registra un SKU nuevo en el catálogo."
      }
      submitLabel={isEdit ? "Guardar cambios" : "Crear producto"}
      pendingLabel="Guardando…"
      isPending={isPending}
      onClose={onClose}
      onSubmit={handleSubmit}
    >
      <div>
        <label className={labelClass} htmlFor="product-sku">
          SKU <span className="text-signal-600">*</span>
        </label>
        <input
          id="product-sku"
          // eslint-disable-next-line jsx-a11y/no-autofocus
          autoFocus
          className={fieldClass}
          type="text"
          maxLength={50}
          value={sku}
          onChange={(event) => setSku(event.currentTarget.value)}
          placeholder="LAP-IND-001"
        />
        <p className={hintClass}>Único en todo el ERP (máx. 50 caracteres).</p>
      </div>

      <div>
        <label className={labelClass} htmlFor="product-name">
          Nombre <span className="text-signal-600">*</span>
        </label>
        <input
          id="product-name"
          className={fieldClass}
          type="text"
          maxLength={200}
          value={name}
          onChange={(event) => setName(event.currentTarget.value)}
          placeholder="Laptop Industrial Rugged"
        />
      </div>

      <div>
        <label className={labelClass} htmlFor="product-description">
          Descripción{" "}
          <span className="font-normal text-ink-500">(opcional)</span>
        </label>
        <textarea
          id="product-description"
          className={`${fieldClass} resize-none`}
          rows={3}
          value={description}
          onChange={(event) => setDescription(event.currentTarget.value)}
          placeholder="Detalle del artículo, presentación o uso previsto."
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className={labelClass} htmlFor="product-price">
            Precio base <span className="text-signal-600">*</span>
          </label>
          <input
            id="product-price"
            className={fieldClass}
            type="text"
            inputMode="decimal"
            value={unitPrice}
            onChange={(event) => setUnitPrice(event.currentTarget.value)}
            placeholder="1899.90"
          />
        </div>
        <div>
          <label className={labelClass} htmlFor="product-minimum">
            Stock mínimo
          </label>
          <input
            id="product-minimum"
            className={fieldClass}
            type="number"
            inputMode="numeric"
            min={0}
            step={1}
            value={minimumStock}
            onChange={(event) => setMinimumStock(event.currentTarget.value)}
          />
        </div>
      </div>

      <ActiveSwitch
        checked={isActive}
        onChange={setIsActive}
        label="Producto activo"
        hint="Los productos inactivos no deberían recibir movimientos nuevos."
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
