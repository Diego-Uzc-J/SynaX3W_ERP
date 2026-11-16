/**
 * Cliente HTTP único del ERP.
 *
 * Añade el `Bearer` token desde el store, traduce los errores de FastAPI y,
 * ante un `401`, intenta renovar el access token una sola vez con
 * `POST /api/v1/users/auth/refresh` antes de reintentar la petición original.
 * Si la renovación falla, limpia la sesión; las guardias de ruta se encargan de
 * devolver al login.
 */

import {
  clearSession,
  getAuthState,
  setAccessToken,
} from "../store/authStore";
import { API_BASE_URL } from "./config";

const REFRESH_PATH = "/api/v1/users/auth/refresh";

export interface ApiRequestOptions extends RequestInit {
  /** Omite el Bearer y la renovación (login, captcha). */
  skipAuth?: boolean;
}

/** Error HTTP con el status y el payload devuelto por la API. */
export class ApiError extends Error {
  readonly status: number;
  readonly payload: unknown;

  constructor(message: string, status: number, payload: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

/** Extrae el `detail` de FastAPI, incluidos los 422 con lista de errores. */
export function extractErrorMessage(payload: unknown, status: number): string {
  if (isRecord(payload) && "detail" in payload) {
    const detail = payload.detail;
    if (typeof detail === "string" && detail.length > 0) {
      return detail;
    }
    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => {
          if (!isRecord(item)) {
            return String(item);
          }
          const location = Array.isArray(item.loc)
            ? item.loc
                .filter((part) => part !== "body")
                .map(String)
                .join(".")
            : "";
          const message = typeof item.msg === "string" ? item.msg : "";
          if (message === "") {
            return location;
          }
          return location === "" ? message : `${location}: ${message}`;
        })
        .filter((message) => message.length > 0);
      if (messages.length > 0) {
        return messages.join("; ");
      }
    }
  }
  if (status === 429) {
    return "Demasiadas peticiones. Espera un momento antes de reintentar.";
  }
  return `Error HTTP ${status} al comunicarse con la API`;
}

async function send(
  path: string,
  init: RequestInit,
  accessToken: string | null,
): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (typeof init.body === "string" && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (accessToken !== null) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }
  return fetch(`${API_BASE_URL}${path}`, { ...init, headers });
}

// Una única renovación compartida evita que varias peticiones simultáneas
// consuman el refresh token en paralelo.
let refreshInFlight: Promise<string | null> | null = null;

async function requestNewAccessToken(): Promise<string | null> {
  const { refreshToken } = getAuthState();
  if (refreshToken === null) {
    return null;
  }
  try {
    const response = await fetch(`${API_BASE_URL}${REFRESH_PATH}`, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (!response.ok) {
      return null;
    }
    const payload: unknown = await response.json();
    if (
      !isRecord(payload) ||
      typeof payload.access_token !== "string" ||
      payload.access_token === ""
    ) {
      return null;
    }
    setAccessToken(payload.access_token);
    return payload.access_token;
  } catch {
    return null;
  }
}

function refreshAccessToken(): Promise<string | null> {
  if (refreshInFlight === null) {
    refreshInFlight = requestNewAccessToken().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

async function parseErrorPayload(response: Response): Promise<unknown> {
  try {
    return (await response.json()) as unknown;
  } catch {
    return undefined;
  }
}

/**
 * Ejecuta una petición autenticada y devuelve el JSON tipado.
 *
 * @throws {ApiError} si la respuesta no es 2xx.
 */
export async function apiRequest<T>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  const { skipAuth = false, ...init } = options;

  let response = await send(
    path,
    init,
    skipAuth ? null : getAuthState().accessToken,
  );

  if (response.status === 401 && !skipAuth) {
    const renewed = await refreshAccessToken();
    if (renewed === null) {
      clearSession();
    } else {
      response = await send(path, init, renewed);
      if (response.status === 401) {
        clearSession();
      }
    }
  }

  if (!response.ok) {
    const payload = await parseErrorPayload(response);
    // La cuenta fue desactivada mientras la sesión seguía abierta: no tiene
    // sentido conservar tokens que la API ya rechaza en todos los módulos.
    if (
      response.status === 403 &&
      isRecord(payload) &&
      payload.detail === "Usuario inactivo"
    ) {
      clearSession();
    }
    throw new ApiError(
      extractErrorMessage(payload, response.status),
      response.status,
      payload,
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  try {
    return (await response.json()) as T;
  } catch {
    return undefined as T;
  }
}
