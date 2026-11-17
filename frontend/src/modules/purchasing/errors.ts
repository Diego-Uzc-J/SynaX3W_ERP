/** Traducción de errores de negocio de compras a mensajes accionables. */

/** Mensaje legible de un error de mutación o consulta. */
export function errorMessage(error: unknown): string | null {
  if (error instanceof Error && error.message.trim() !== "") {
    return error.message;
  }
  return null;
}

/**
 * Pista derivada del mensaje del backend.
 *
 * El router de compras devuelve textos explícitos para proveedores inactivos,
 * sobre-recepciones y cierres; aquí se añade qué hacer a continuación sin
 * ocultar el mensaje original.
 */
export function errorHint(message: string): string | null {
  const normalized = message.toLowerCase();
  if (normalized.includes("pendientes") || normalized.includes("sobre")) {
    return (
      "La cantidad supera lo pendiente de la línea. Ajusta las cantidades " +
      "recibidas o consulta el detalle de la orden antes de reintentar."
    );
  }
  if (normalized.includes("activo") || normalized.includes("inactivo")) {
    return (
      "El proveedor o producto está inactivo. Reactívalo en su módulo antes " +
      "de guardar la orden o registrar la recepción."
    );
  }
  if (normalized.includes("movimientos de inventario")) {
    return (
      "La orden ya tiene recepciones: no se puede cancelar. Cierra forzosamente " +
      "la orden (FORCE_CLOSED) para liberar el saldo pendiente."
    );
  }
  if (normalized.includes("force_closed") || normalized.includes("forzar")) {
    return "El cierre forzoso solo está disponible desde APPROVED o PARTIALLY_RECEIVED.";
  }
  if (normalized.includes("bodega") || normalized.includes("warehouse")) {
    return "Selecciona una bodega activa en inventario y vuelve a intentarlo.";
  }
  if (normalized.includes("número de factura") || normalized.includes("factura")) {
    return "Revisa el número de factura del proveedor: debe ser único por proveedor.";
  }
  return null;
}
