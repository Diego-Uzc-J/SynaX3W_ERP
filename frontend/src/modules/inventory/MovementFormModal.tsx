import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";

import { useCreateMovement } from "../../api/inventory";
import type {
  MovementType,
  Product,
  StockMovement,
  StockMovementCreate,
  Warehouse,
} from "../../api/inventory";
import { MOVEMENT_HINTS, MOVEMENT_LABELS } from "./constants";

const MOVEMENT_ORDER: readonly MovementType[] = [
  "INBOUND",
  "OUTBOUND",
  "TRANSFER",
  "ADJUSTMENT",
];

type AdjustmentDirection = "increase" | "decrease";

interface MovementFormModalProps {
  open: boolean;
  products: readonly Product[];
  warehouses: readonly Warehouse[];
  initialProductId: number | null;
  onClose: () => void;
  onCreated: (movement: StockMovement) => void;
}

const labelClass = "mb-1.5 block text-xs font-semibold text-ink-700";
const fieldClass =
  "w-full border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-950 " +
  "placeholder:text-concrete-400 focus:border-ink-950";

export default function MovementFormModal({
  open,
  products,
  warehouses,
  initialProductId,
  onClose,
  onCreated,
}: MovementFormModalProps) {
  const [movementType, setMovementType] = useState<MovementType>("INBOUND");
  const [productId, setProductId] = useState("");
  const [sourceId, setSourceId] = useState("");
  const [destinationId, setDestinationId] = useState("");
  const [adjustmentWarehouseId, setAdjustmentWarehouseId] = useState("");
  const [adjustmentDirection, setAdjustmentDirection] =
    useState<AdjustmentDirection>("increase");
  const [quantity, setQuantity] = useState("");
  const [referenceDocument, setReferenceDocument] = useState("");
  const [notes, setNotes] = useState("");
  const [createdBy, setCreatedBy] = useState("operador");
  const [formError, setFormError] = useState<string | null>(null);

  const { mutate, isPending, error, reset } = useCreateMovement();
  const firstFieldRef = useRef<HTMLSelectElement>(null);

  useEffect(() => {
    if (!open) {
      return;
    }
    setMovementType("INBOUND");
    setProductId(initialProductId === null ? "" : String(initialProductId));
    setSourceId("");
    setDestinationId("");
    setAdjustmentWarehouseId("");
    setAdjustmentDirection("increase");
    setQuantity("");
    setReferenceDocument("");
    setNotes("");
    setCreatedBy("operador");
    setFormError(null);
    reset();
  }, [open, initialProductId, reset]);

  useEffect(() => {
    if (!open) {
      return;
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const frame = requestAnimationFrame(() => firstFieldRef.current?.focus());
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
      cancelAnimationFrame(frame);
    };
  }, [open, onClose]);

  if (!open) {
    return null;
  }

  function validate(): string | null {
    if (productId === "") {
      return "Selecciona un producto.";
    }
    const parsedQuantity = Number(quantity);
    if (!Number.isInteger(parsedQuantity) || parsedQuantity <= 0) {
      return "La cantidad debe ser un entero mayor que cero.";
    }
    if (referenceDocument.trim() === "") {
      return "Indica el documento de referencia.";
    }
    if (createdBy.trim() === "") {
      return "Indica quién registra el movimiento.";
    }
    if (movementType === "INBOUND" && destinationId === "") {
      return "Selecciona la bodega de destino.";
    }
    if (movementType === "OUTBOUND" && sourceId === "") {
      return "Selecciona la bodega de origen.";
    }
    if (movementType === "TRANSFER") {
      if (sourceId === "" || destinationId === "") {
        return "Selecciona la bodega de origen y la de destino.";
      }
      if (sourceId === destinationId) {
        return "La bodega de origen y la de destino deben ser distintas.";
      }
    }
    if (movementType === "ADJUSTMENT" && adjustmentWarehouseId === "") {
      return "Selecciona la bodega que quieres ajustar.";
    }    return null;
  }

  function buildPayload(): StockMovementCreate {
    const payload: StockMovementCreate = {
      product_id: Number(productId),
      movement_type: movementType,
      quantity: Number(quantity),
      reference_document: referenceDocument.trim(),
      created_by: createdBy.trim(),
    };

    const trimmedNotes = notes.trim();
    if (trimmedNotes !== "") {
      payload.notes = trimmedNotes;
    }

    if (movementType === "INBOUND") {
      payload.warehouse_destination_id = Number(destinationId);
    } else if (movementType === "OUTBOUND") {
      payload.warehouse_source_id = Number(sourceId);
    } else if (movementType === "TRANSFER") {
      payload.warehouse_source_id = Number(sourceId);
      payload.warehouse_destination_id = Number(destinationId);
    } else if (adjustmentDirection === "increase") {
      payload.warehouse_destination_id = Number(adjustmentWarehouseId);
    } else {
      payload.warehouse_source_id = Number(adjustmentWarehouseId);
    }

    return payload;
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = validate();
    if (message !== null) {
      setFormError(message);
      return;
    }
    setFormError(null);
    mutate(buildPayload(), {
      onSuccess: (movement) => onCreated(movement),
    });
  }

  const serverError = error instanceof Error ? error.message : null;
  const visibleError = formError ?? serverError;

  function renderWarehouseOptions() {
    return warehouses.map((warehouse) => (
      <option key={warehouse.id} value={String(warehouse.id)}>
        {warehouse.code} — {warehouse.name}
      </option>
    ));
  }

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end"
      role="dialog"
      aria-modal="true"
      aria-labelledby="movement-form-title"
    >
      <button
        type="button"
        aria-label="Cerrar formulario"
        className="backdrop-enter absolute inset-0 cursor-default bg-ink-950/55"
        onClick={onClose}
      />

      <div className="sheet-enter relative flex h-full w-full max-w-lg flex-col bg-concrete-50 shadow-2xl">
        <form
          onSubmit={handleSubmit}
          className="flex h-full min-h-0 flex-col"
          noValidate
        >
          <header className="flex items-start justify-between gap-4 border-b border-concrete-200 bg-white px-5 py-4">
            <div>
              <h2
                id="movement-form-title"
                className="text-xl font-bold tracking-tight"
              >
                Registrar movimiento
              </h2>
              <p className="mt-0.5 text-sm text-ink-500">
                El saldo de la bodega se actualiza al guardar.
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="-mr-1 grid size-8 place-items-center border border-transparent text-xl leading-none text-ink-500 hover:border-concrete-200 hover:text-ink-950"
              aria-label="Cerrar"
            >
              ×
            </button>
          </header>

          <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-5 py-5">
            <fieldset>
              <legend className={labelClass}>Tipo de movimiento</legend>
              <div className="grid grid-cols-2 gap-2">
                {MOVEMENT_ORDER.map((type) => {
                  const active = type === movementType;
                  return (
                    <button
                      key={type}
                      type="button"
                      aria-pressed={active}
                      onClick={() => {
                        setMovementType(type);
                        setFormError(null);
                      }}
                      className={[
                        "border p-3 text-left transition-colors",
                        active
                          ? "border-ink-950 bg-ink-950 text-concrete-50"
                          : "border-concrete-200 bg-white text-ink-950 hover:border-ink-500",
                      ].join(" ")}
                    >
                      <span className="block text-sm font-semibold">
                        {MOVEMENT_LABELS[type]}
                      </span>
                      <span
                        className={[
                          "mt-0.5 block text-xs",
                          active ? "text-concrete-400" : "text-ink-500",
                        ].join(" ")}
                      >
                        {MOVEMENT_HINTS[type]}
                      </span>
                    </button>
                  );
                })}
              </div>
            </fieldset>

            <div>
              <label className={labelClass} htmlFor="movement-product">
                Producto
              </label>
              <select
                ref={firstFieldRef}
                id="movement-product"
                className={fieldClass}
                value={productId}
                onChange={(event) => setProductId(event.currentTarget.value)}
              >
                <option value="">Selecciona un producto</option>
                {products.map((product) => (
                  <option key={product.id} value={String(product.id)}>
                    {product.sku} — {product.name}
                  </option>
                ))}
              </select>
            </div>

            {movementType === "ADJUSTMENT" ? (
              <div>
                <span className={labelClass}>Sentido del ajuste</span>
                <div className="grid grid-cols-2 border border-concrete-200 bg-white">
                  {(
                    [
                      ["increase", "Sumar unidades"],
                      ["decrease", "Restar unidades"],
                    ] as const
                  ).map(([value, text]) => (
                    <button
                      key={value}
                      type="button"
                      aria-pressed={adjustmentDirection === value}
                      onClick={() => setAdjustmentDirection(value)}
                      className={[
                        "px-3 py-2 text-sm font-semibold transition-colors",
                        adjustmentDirection === value
                          ? "bg-ink-950 text-concrete-50"
                          : "text-ink-500 hover:text-ink-950",
                      ].join(" ")}
                    >
                      {text}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            {movementType === "INBOUND" || movementType === "TRANSFER" ? (
              <div>
                <label className={labelClass} htmlFor="movement-destination">
                  Bodega de destino
                </label>
                <select
                  id="movement-destination"
                  className={fieldClass}
                  value={destinationId}
                  onChange={(event) =>
                    setDestinationId(event.currentTarget.value)
                  }
                >
                  <option value="">Selecciona una bodega</option>
                  {renderWarehouseOptions()}
                </select>
              </div>
            ) : null}

            {movementType === "OUTBOUND" || movementType === "TRANSFER" ? (
              <div>
                <label className={labelClass} htmlFor="movement-source">
                  Bodega de origen
                </label>
                <select
                  id="movement-source"
                  className={fieldClass}
                  value={sourceId}
                  onChange={(event) => setSourceId(event.currentTarget.value)}
                >
                  <option value="">Selecciona una bodega</option>
                  {renderWarehouseOptions()}
                </select>
              </div>
            ) : null}

            {movementType === "ADJUSTMENT" ? (
              <div>
                <label className={labelClass} htmlFor="movement-adjustment">
                  Bodega
                </label>
                <select
                  id="movement-adjustment"
                  className={fieldClass}
                  value={adjustmentWarehouseId}
                  onChange={(event) =>
                    setAdjustmentWarehouseId(event.currentTarget.value)
                  }
                >
                  <option value="">Selecciona una bodega</option>
                  {renderWarehouseOptions()}
                </select>
              </div>
            ) : null}

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={labelClass} htmlFor="movement-quantity">
                  Cantidad
                </label>
                <input
                  id="movement-quantity"
                  className={fieldClass}
                  type="number"
                  inputMode="numeric"
                  min={1}
                  step={1}
                  value={quantity}
                  onChange={(event) => setQuantity(event.currentTarget.value)}
                  placeholder="0"
                />
              </div>
              <div>
                <label className={labelClass} htmlFor="movement-reference">
                  Documento
                </label>
                <input
                  id="movement-reference"
                  className={fieldClass}
                  type="text"
                  maxLength={100}
                  value={referenceDocument}
                  onChange={(event) =>
                    setReferenceDocument(event.currentTarget.value)
                  }
                  placeholder="OC-2026-001"
                />
              </div>
            </div>

            <div>
              <label className={labelClass} htmlFor="movement-created-by">
                Registrado por
              </label>
              <input
                id="movement-created-by"
                className={fieldClass}
                type="text"
                maxLength={150}
                value={createdBy}
                onChange={(event) => setCreatedBy(event.currentTarget.value)}
              />
            </div>

            <div>
              <label className={labelClass} htmlFor="movement-notes">
                Notas <span className="font-normal text-ink-500">(opcional)</span>
              </label>
              <textarea
                id="movement-notes"
                className={`${fieldClass} resize-none`}
                rows={2}
                value={notes}
                onChange={(event) => setNotes(event.currentTarget.value)}
              />
            </div>

            {visibleError !== null ? (
              <p
                role="alert"
                className="border-l-2 border-signal-500 bg-signal-100 px-3 py-2 text-sm font-medium text-signal-600"
              >
                {visibleError}
              </p>
            ) : null}
          </div>

          <footer className="flex items-center justify-end gap-3 border-t border-concrete-200 bg-white px-5 py-4">
            <button
              type="button"
              onClick={onClose}
              className="border border-concrete-200 px-4 py-2 text-sm font-semibold text-ink-700 hover:border-ink-500 hover:text-ink-950"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={isPending}
              className="bg-signal-500 px-4 py-2 text-sm font-semibold text-white hover:bg-signal-600 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isPending ? "Guardando…" : "Guardar movimiento"}
            </button>
          </footer>
        </form>
      </div>
    </div>
  );
}
