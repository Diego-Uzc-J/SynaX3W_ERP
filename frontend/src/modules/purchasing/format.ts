/** Formateadores y aritmética monetaria de las vistas de compras. */

const moneyFormatter = new Intl.NumberFormat("es-CO", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const dateFormatter = new Intl.DateTimeFormat("es-CO", { dateStyle: "medium" });

/** Los importes llegan como string (Pydantic serializa `Decimal` así). */
export function formatMoney(value: string | number): string {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? moneyFormatter.format(parsed) : String(value);
}

export function formatDate(value: string): string {
  const parsed = new Date(`${value}T00:00:00`);
  return Number.isNaN(parsed.getTime()) ? value : dateFormatter.format(parsed);
}

/** Acepta coma decimal y separadores de miles, y normaliza al punto de la API. */
export function normalizeDecimal(value: string): string {
  const trimmed = value.trim();
  if (!trimmed.includes(",")) {
    return trimmed;
  }
  return trimmed.replace(/\./g, "").replace(",", ".");
}

/** Convierte un importe escrito por el usuario a número (máx. 14,2). */
export function parseAmount(value: string): number | null {
  const normalized = normalizeDecimal(value);
  if (!/^\d{1,12}(\.\d{1,2})?$/.test(normalized)) {
    return null;
  }
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

/** Porcentaje de impuesto entre 0 y 100 con hasta dos decimales. */
export function parseTaxRate(value: string): number | null {
  const parsed = parseAmount(value);
  if (parsed === null || parsed > 100) {
    return null;
  }
  return parsed;
}

/** Cantidad entera positiva. */
export function parseQuantity(value: string): number | null {
  const trimmed = value.trim();
  if (!/^\d{1,9}$/.test(trimmed)) {
    return null;
  }
  const parsed = Number(trimmed);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

/** Fija dos decimales sin notación científica para el payload de la API. */
export function moneyString(value: number): string {
  return value.toFixed(2);
}

export interface LineAmounts {
  subtotalCents: number;
  taxCents: number;
  totalCents: number;
}

/**
 * Calcula subtotal e impuestos en centavos para evitar errores de coma flotante.
 *
 * El backend redondea con `ROUND_HALF_UP`; `Math.round` replica ese
 * comportamiento para los importes positivos que maneja la vista.
 */
export function computeLine(
  quantity: number,
  unitPrice: number,
  taxRate: number,
): LineAmounts {
  const unitCents = Math.round(unitPrice * 100);
  const subtotalCents = quantity * unitCents;
  const taxBasisPoints = Math.round(taxRate * 100);
  const taxCents = Math.round((subtotalCents * taxBasisPoints) / 10_000);
  return {
    subtotalCents,
    taxCents,
    totalCents: subtotalCents + taxCents,
  };
}

export function formatCents(cents: number): string {
  return moneyFormatter.format(cents / 100);
}

function toIsoDate(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/** Fecha local de hoy en formato `YYYY-MM-DD` (sin desfase UTC). */
export function todayIso(): string {
  return toIsoDate(new Date());
}

/** Suma días a la fecha local de hoy y devuelve `YYYY-MM-DD`. */
export function todayPlusDays(days: number): string {
  const value = new Date();
  value.setDate(value.getDate() + days);
  return toIsoDate(value);
}

/** Suma días a una fecha `YYYY-MM-DD` (para sugerir el vencimiento). */
export function addDaysToIso(value: string, days: number): string {
  const parsed = new Date(`${value}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  parsed.setDate(parsed.getDate() + days);
  return toIsoDate(parsed);
}
