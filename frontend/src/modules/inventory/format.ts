/** Formateadores compartidos por las vistas del módulo de inventario. */

const priceFormatter = new Intl.NumberFormat("es-CO", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** Los precios llegan como string (Pydantic serializa `Decimal` así). */
export function formatPrice(value: string | number): string {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? priceFormatter.format(parsed) : String(value);
}

const dateFormatter = new Intl.DateTimeFormat("es-CO", { dateStyle: "medium" });

export function formatDate(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : dateFormatter.format(parsed);
}
