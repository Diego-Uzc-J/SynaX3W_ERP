import { useEffect, useId } from "react";
import type { FormEvent, ReactNode } from "react";

interface FormSheetProps {
  open: boolean;
  title: string;
  subtitle?: string;
  submitLabel: string;
  pendingLabel: string;
  isPending: boolean;
  onClose: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  children: ReactNode;
}

/**
 * Panel lateral usado por los formularios de alta y edición.
 *
 * Se monta solo cuando `open` es verdadero, cierra con Escape, bloquea el
 * scroll del documento y concentra el manejo del submit y del estado pendiente.
 */
export default function FormSheet({
  open,
  title,
  subtitle,
  submitLabel,
  pendingLabel,
  isPending,
  onClose,
  onSubmit,
  children,
}: FormSheetProps) {
  const titleId = useId();

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
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [open, onClose]);

  if (!open) {
    return null;
  }

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
    >
      <button
        type="button"
        aria-label="Cerrar formulario"
        className="backdrop-enter absolute inset-0 cursor-default bg-ink-950/55"
        onClick={onClose}
      />

      <div className="sheet-enter relative flex h-full w-full max-w-lg flex-col bg-concrete-50 shadow-2xl">
        <form
          onSubmit={onSubmit}
          noValidate
          className="flex h-full min-h-0 flex-col"
        >
          <header className="flex items-start justify-between gap-4 border-b border-concrete-200 bg-white px-5 py-4">
            <div>
              <h2 id={titleId} className="text-xl font-bold tracking-tight">
                {title}
              </h2>
              {subtitle === undefined ? null : (
                <p className="mt-0.5 text-sm text-ink-500">{subtitle}</p>
              )}
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="Cerrar"
              className="-mr-1 grid size-8 place-items-center border border-transparent text-xl leading-none text-ink-500 hover:border-concrete-200 hover:text-ink-950"
            >
              ×
            </button>
          </header>

          <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-5 py-5">
            {children}
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
              className="bg-signal-500 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-signal-600 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isPending ? pendingLabel : submitLabel}
            </button>
          </footer>
        </form>
      </div>
    </div>
  );
}
