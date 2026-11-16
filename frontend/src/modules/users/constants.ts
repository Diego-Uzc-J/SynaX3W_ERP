import type { RoleName } from "../../store/authStore";

/** Nombres legibles de los siete roles del ERP. */
export const ROLE_LABELS: Record<RoleName, string> = {
  administrator: "Administrador",
  inventory: "Inventario",
  sales: "Ventas",
  purchasing: "Compras",
  accounting: "Contabilidad",
  hr: "Recursos humanos",
  manufacturing: "Manufactura",
};

export const ROLE_ORDER: readonly RoleName[] = [
  "administrator",
  "inventory",
  "sales",
  "purchasing",
  "accounting",
  "hr",
  "manufacturing",
] as const;

export const ROLE_HINTS: Record<RoleName, string> = {
  administrator: "Acceso total y administración de cuentas.",
  inventory: "Inventario completo y catálogo.",
  sales: "Ventas y lectura de inventario.",
  purchasing: "Compras y lectura de inventario.",
  accounting: "Contabilidad y lectura de ventas/compras.",
  hr: "Gestión exclusiva de personal.",
  manufacturing: "Manufactura y lectura de inventario.",
};

const dateFormatter = new Intl.DateTimeFormat("es-CO", {
  day: "2-digit",
  month: "short",
  year: "numeric",
});

export function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : dateFormatter.format(date);
}

export function initials(fullName: string): string {
  const parts = fullName
    .trim()
    .split(/\s+/)
    .filter((part) => part.length > 0);
  const first = parts[0]?.[0] ?? "?";
  const second = parts.length > 1 ? parts[parts.length - 1]?.[0] ?? "" : "";
  return `${first}${second}`.toUpperCase();
}
