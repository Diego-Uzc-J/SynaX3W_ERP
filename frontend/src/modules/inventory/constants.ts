import type { MovementType } from "../../api/inventory";

export const MOVEMENT_LABELS: Record<MovementType, string> = {
  INBOUND: "Entrada",
  OUTBOUND: "Salida",
  TRANSFER: "Transferencia",
  ADJUSTMENT: "Ajuste",
};

export const MOVEMENT_HINTS: Record<MovementType, string> = {
  INBOUND: "Suma unidades a una bodega.",
  OUTBOUND: "Descuenta unidades de una bodega.",
  TRANSFER: "Mueve unidades entre dos bodegas.",
  ADJUSTMENT: "Corrige el saldo de una bodega.",
};
