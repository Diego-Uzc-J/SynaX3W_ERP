/** Traducción de errores del backend a mensajes accionables para la vista. */

/** Mensaje legible de un error de mutación o consulta. */
export function errorMessage(error: unknown): string | null {
  if (error instanceof Error && error.message.trim() !== "") {
    return error.message;
  }
  return null;
}

/**
 * Pista de negocio derivada del mensaje del backend.
 *
 * El backend responde con textos explícitos para crédito, stock y facturas;
 * aquí se añade qué hacer a continuación sin ocultar el mensaje original.
 */
export function errorHint(message: string): string | null {
  const normalized = message.toLowerCase();
  if (normalized.includes("crédito") || normalized.includes("credito")) {
    return (
      "El total supera el cupo disponible del cliente. Reduce el pedido, " +
      "registra un pago o amplía el límite de crédito."
    );
  }
  if (
    normalized.includes("stock insuficiente") ||
    normalized.includes("existencias")
  ) {
    return (
      "No hay unidades suficientes en la bodega seleccionada. Repón " +
      "inventario, elige otra bodega o ajusta las cantidades."
    );
  }
  if (normalized.includes("factura")) {
    return (
      "Las facturas emitidas son inmutables: corrige con una anulación " +
      "(VOID) o una nota crédito en lugar de editar o borrar."
    );
  }
  if (normalized.includes("inactivo")) {
    return "Reactiva el cliente antes de registrar nuevas operaciones.";
  }
  return null;
}
