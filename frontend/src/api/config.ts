/** Configuración compartida del cliente HTTP. */

const configuredBaseUrl = import.meta.env?.VITE_API_URL?.trim();
const DEFAULT_API_BASE_URL = "http://localhost:8000";

/** URL base del backend, sin barra final. */
export const API_BASE_URL = (configuredBaseUrl || DEFAULT_API_BASE_URL).replace(
  /\/+$/,
  "",
);

/** Serializa filtros omitiendo valores vacíos, nulos o indefinidos. */
export function buildQuery(params: object): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(
    params as Record<string, unknown>,
  )) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    search.set(key, String(value));
  }
  const queryString = search.toString();
  return queryString ? `?${queryString}` : "";
}
