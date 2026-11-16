/**
 * Capa de integración del módulo de Usuarios y Seguridad.
 *
 * Contratos derivados de `backend/src/modules/users/schemas.py` y de
 * `specs/users_spec.md` (sección 5). El login y el captcha se ejecutan sin
 * Bearer; el resto pasa por el cliente común, que renueva el token ante un 401.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { AuthRole, AuthUser, RoleName } from "../store/authStore";
import { apiRequest } from "./client";
import { buildQuery } from "./config";

const USERS_PATH = "/api/v1/users";

// --------------------------------------------------------------------------- //
// Tipos de dominio
// --------------------------------------------------------------------------- //

export type { AuthRole, AuthUser, RoleName };

export interface CaptchaChallenge {
  question: string;
  captcha_token: string;
}

export interface LoginPayload {
  identifier: string;
  password: string;
  captcha_token: string;
  captcha_answer: number;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  role: RoleName;
  allowed_modules: string[];
}

export interface RefreshResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface UserCreate {
  email: string;
  username: string;
  full_name: string;
  password: string;
  role_id: string;
}

/** Actualización parcial: el backend rechaza cualquier campo privilegiado. */
export interface UserUpdate {
  email?: string;
  username?: string;
  full_name?: string;
  role_id?: string;
  is_active?: boolean;
}

export interface PasswordUpdate {
  new_password: string;
}

export interface UserFilters {
  skip?: number;
  limit?: number;
  role?: RoleName;
  is_active?: boolean;
  search?: string;
}

// --------------------------------------------------------------------------- //
// Autenticación — /api/v1/users/auth
// --------------------------------------------------------------------------- //

export function getCaptcha(): Promise<CaptchaChallenge> {
  return apiRequest<CaptchaChallenge>(`${USERS_PATH}/auth/captcha`, {
    skipAuth: true,
  });
}

export function login(payload: LoginPayload): Promise<LoginResponse> {
  return apiRequest<LoginResponse>(`${USERS_PATH}/auth/login`, {
    method: "POST",
    body: JSON.stringify(payload),
    skipAuth: true,
  });
}

export function refreshSession(refreshToken: string): Promise<RefreshResponse> {
  return apiRequest<RefreshResponse>(`${USERS_PATH}/auth/refresh`, {
    method: "POST",
    body: JSON.stringify({ refresh_token: refreshToken }),
    skipAuth: true,
  });
}

export function getMe(): Promise<AuthUser> {
  return apiRequest<AuthUser>(`${USERS_PATH}/auth/me`);
}

// --------------------------------------------------------------------------- //
// Administración — /api/v1/users
// --------------------------------------------------------------------------- //

export function listRoles(): Promise<AuthRole[]> {
  return apiRequest<AuthRole[]>(`${USERS_PATH}/roles`);
}

export function listUsers(filters: UserFilters = {}): Promise<AuthUser[]> {
  return apiRequest<AuthUser[]>(`${USERS_PATH}/${buildQuery(filters)}`);
}

export function createUser(payload: UserCreate): Promise<AuthUser> {
  return apiRequest<AuthUser>(`${USERS_PATH}/`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateUser(
  userId: string,
  payload: UserUpdate,
): Promise<AuthUser> {
  return apiRequest<AuthUser>(`${USERS_PATH}/${userId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function resetUserPassword(
  userId: string,
  payload: PasswordUpdate,
): Promise<AuthUser> {
  return apiRequest<AuthUser>(`${USERS_PATH}/${userId}/password`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

// --------------------------------------------------------------------------- //
// Claves de caché y hooks
// --------------------------------------------------------------------------- //

export const usersKeys = {
  all: ["users"] as const,
  captcha: ["users", "captcha"] as const,
  me: ["users", "me"] as const,
  roles: ["users", "roles"] as const,
  usersList: ["users", "list"] as const,
  list: (filters: UserFilters) => ["users", "list", filters] as const,
} as const;

export function useCaptcha() {
  return useQuery({
    queryKey: usersKeys.captcha,
    queryFn: getCaptcha,
    staleTime: 0,
    gcTime: 0,
    retry: 1,
  });
}

export function useRoles(enabled = true) {
  return useQuery({
    queryKey: usersKeys.roles,
    queryFn: listRoles,
    enabled,
    staleTime: 5 * 60_000,
  });
}

export function useUsers(filters: UserFilters = {}) {
  return useQuery({
    queryKey: usersKeys.list(filters),
    queryFn: () => listUsers(filters),
  });
}

export function useCreateUser() {
  const queryClient = useQueryClient();
  return useMutation<AuthUser, Error, UserCreate>({
    mutationFn: createUser,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: usersKeys.usersList });
    },
  });
}

export interface UpdateUserVariables {
  userId: string;
  payload: UserUpdate;
}

export function useUpdateUser() {
  const queryClient = useQueryClient();
  return useMutation<AuthUser, Error, UpdateUserVariables>({
    mutationFn: ({ userId, payload }) => updateUser(userId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: usersKeys.usersList });
      void queryClient.invalidateQueries({ queryKey: usersKeys.me });
    },
  });
}

export interface ResetPasswordVariables {
  userId: string;
  payload: PasswordUpdate;
}

export function useResetUserPassword() {
  const queryClient = useQueryClient();
  return useMutation<AuthUser, Error, ResetPasswordVariables>({
    mutationFn: ({ userId, payload }) => resetUserPassword(userId, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: usersKeys.usersList });
    },
  });
}
