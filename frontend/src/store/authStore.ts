/**
 * Store de autenticación del ERP, sin dependencias externas.
 *
 * Mantiene los tokens y el perfil autenticado en memoria y los persiste en
 * `localStorage` para sobrevivir a una recarga. El estado se consume con
 * `useSyncExternalStore`, de modo que cualquier vista reacciona a login,
 * refresco de token o cierre de sesión.
 *
 * Los permisos son una ayuda de navegación: la autorización real siempre la
 * impone el backend con `require_roles`.
 */

import { useSyncExternalStore } from "react";

// --------------------------------------------------------------------------- //
// Tipos de dominio
// --------------------------------------------------------------------------- //

export const ROLE_NAMES = [
  "administrator",
  "inventory",
  "sales",
  "purchasing",
  "accounting",
  "hr",
  "manufacturing",
] as const;

export type RoleName = (typeof ROLE_NAMES)[number];

export interface AuthRole {
  id: string;
  name: RoleName;
  description: string;
  allowed_modules: string[];
}

export interface AuthUser {
  id: string;
  email: string;
  username: string;
  full_name: string;
  is_active: boolean;
  role: AuthRole;
  created_at: string;
  updated_at: string;
}

export interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: AuthUser | null;
}

export interface AuthTokens {
  accessToken: string;
  refreshToken: string;
}

export interface AuthSession extends AuthTokens {
  user: AuthUser;
}

// --------------------------------------------------------------------------- //
// Persistencia y validación defensiva
// --------------------------------------------------------------------------- //

const STORAGE_KEY = "synapsisx.erp.auth.v1";

const EMPTY_STATE: AuthState = {
  accessToken: null,
  refreshToken: null,
  user: null,
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isRoleName(value: unknown): value is RoleName {
  return (
    typeof value === "string" &&
    (ROLE_NAMES as readonly string[]).includes(value)
  );
}

function parseRole(value: unknown): AuthRole | null {
  if (!isRecord(value) || !isRoleName(value.name)) {
    return null;
  }
  const modules = value.allowed_modules;
  if (
    typeof value.id !== "string" ||
    typeof value.description !== "string" ||
    !Array.isArray(modules) ||
    !modules.every((module) => typeof module === "string")
  ) {
    return null;
  }
  return {
    id: value.id,
    name: value.name,
    description: value.description,
    allowed_modules: modules.filter(
      (module): module is string => typeof module === "string",
    ),
  };
}

function parseUser(value: unknown): AuthUser | null {
  if (!isRecord(value)) {
    return null;
  }
  const role = parseRole(value.role);
  if (
    role === null ||
    typeof value.id !== "string" ||
    typeof value.email !== "string" ||
    typeof value.username !== "string" ||
    typeof value.full_name !== "string" ||
    typeof value.is_active !== "boolean" ||
    typeof value.created_at !== "string" ||
    typeof value.updated_at !== "string"
  ) {
    return null;
  }
  return {
    id: value.id,
    email: value.email,
    username: value.username,
    full_name: value.full_name,
    is_active: value.is_active,
    role,
    created_at: value.created_at,
    updated_at: value.updated_at,
  };
}

function readPersistedSession(): AuthState {
  if (typeof window === "undefined") {
    return EMPTY_STATE;
  }
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === null) {
      return EMPTY_STATE;
    }
    const parsed: unknown = JSON.parse(raw);
    if (!isRecord(parsed)) {
      return EMPTY_STATE;
    }
    const user = parseUser(parsed.user);
    if (
      typeof parsed.accessToken !== "string" ||
      typeof parsed.refreshToken !== "string" ||
      user === null
    ) {
      return EMPTY_STATE;
    }
    return {
      accessToken: parsed.accessToken,
      refreshToken: parsed.refreshToken,
      user,
    };
  } catch {
    return EMPTY_STATE;
  }
}

function persistSession(state: AuthState): void {
  if (typeof window === "undefined") {
    return;
  }
  try {
    if (
      state.accessToken === null ||
      state.refreshToken === null ||
      state.user === null
    ) {
      window.localStorage.removeItem(STORAGE_KEY);
      return;
    }
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        accessToken: state.accessToken,
        refreshToken: state.refreshToken,
        user: state.user,
      }),
    );
  } catch {
    // Un almacenamiento lleno o bloqueado no debe tumbar la sesión en memoria.
  }
}

// --------------------------------------------------------------------------- //
// Estado y suscripciones
// --------------------------------------------------------------------------- //

let state: AuthState = readPersistedSession();
const listeners = new Set<() => void>();

function commit(next: AuthState): void {
  state = next;
  persistSession(state);
  for (const listener of listeners) {
    listener();
  }
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): AuthState {
  return state;
}

/** Hook principal: devuelve el estado completo de autenticación. */
export function useAuth(): AuthState {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

export function getAuthState(): AuthState {
  return state;
}

// --------------------------------------------------------------------------- //
// Acciones
// --------------------------------------------------------------------------- //

/** Guarda los tokens y conserva el perfil ya cargado, si existe. */
export function setTokens(tokens: AuthTokens): void {
  commit({
    accessToken: tokens.accessToken,
    refreshToken: tokens.refreshToken,
    user: state.user,
  });
}

/** Guarda una sesión completa (login + perfil). */
export function setSession(session: AuthSession): void {
  commit({
    accessToken: session.accessToken,
    refreshToken: session.refreshToken,
    user: session.user,
  });
}

/** Actualiza el perfil sin tocar los tokens (por ejemplo tras `GET /me`). */
export function setUser(user: AuthUser): void {
  commit({ ...state, user });
}

/** Reemplaza solo el access token tras una renovación. */
export function setAccessToken(accessToken: string): void {
  if (state.accessToken === accessToken) {
    return;
  }
  commit({ ...state, accessToken });
}

/** Elimina tokens y perfil de memoria y de `localStorage`. */
export function clearSession(): void {
  if (
    state.accessToken === null &&
    state.refreshToken === null &&
    state.user === null
  ) {
    return;
  }
  commit(EMPTY_STATE);
}

/** Cierre de sesión explícito; el refresh token del backend sigue siendo válido. */
export const logout = clearSession;

// --------------------------------------------------------------------------- //
// Permisos derivados
// --------------------------------------------------------------------------- //

/**
 * Indica si el perfil puede entrar a un módulo.
 *
 * `ADMINISTRATOR` obtiene bypass y un permiso de lectura (`modulo:read`)
 * habilita la navegación de consulta. Para escribir, los componentes deben
 * comprobar el permiso exacto con `canWriteModule`.
 */
export function hasModuleAccess(
  user: AuthUser | null,
  module: string,
): boolean {
  if (user === null || !user.is_active) {
    return false;
  }
  if (user.role.name === "administrator") {
    return true;
  }
  const modules = user.role.allowed_modules;
  return modules.includes(module) || modules.includes(`${module}:read`);
}

export function canWriteModule(
  user: AuthUser | null,
  module: string,
): boolean {
  if (user === null || !user.is_active) {
    return false;
  }
  return (
    user.role.name === "administrator" ||
    user.role.allowed_modules.includes(module)
  );
}
