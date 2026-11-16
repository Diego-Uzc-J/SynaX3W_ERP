import { useEffect } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";

import { ApiError } from "../api/client";
import { getMe } from "../api/users";
import {
  clearSession,
  hasModuleAccess,
  setUser,
  useAuth,
} from "../store/authStore";
import AccessDenied from "./AccessDenied";
import { firstAccessiblePath } from "./modules";
import type { ModuleKey } from "./modules";

/**
 * Valida el token persistido contra `GET /auth/me`.
 *
 * Se ejecuta al entrar al área protegida y cada vez que cambia el access
 * token. Si la cuenta fue desactivada (403) o el refresh falló (401), limpia
 * la sesión y `RequireAuth` redirige al login.
 */
export function SessionValidator() {
  const accessToken = useAuth().accessToken;

  useEffect(() => {
    if (accessToken === null) {
      return;
    }
    let cancelled = false;
    void getMe()
      .then((profile) => {
        if (!cancelled) {
          setUser(profile);
        }
      })
      .catch((error: unknown) => {
        if (
          !cancelled &&
          error instanceof ApiError &&
          (error.status === 401 || error.status === 403)
        ) {
          clearSession();
        }
      });
    return () => {
      cancelled = true;
    };
  }, [accessToken]);

  return null;
}

/** Bloquea cualquier ruta privada sin tokens y perfil cargado. */
export function RequireAuth() {
  const { accessToken, user } = useAuth();
  const location = useLocation();

  if (accessToken === null || user === null) {
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: `${location.pathname}${location.search}` }}
      />
    );
  }

  return (
    <>
      <SessionValidator />
      <Outlet />
    </>
  );
}

/** Exige que `allowed_modules` incluya el módulo de la ruta. */
export function RequireModule({ module }: { module: ModuleKey }) {
  const { user } = useAuth();

  if (user === null) {
    return <Navigate to="/login" replace />;
  }
  if (!hasModuleAccess(user, module)) {
    return <AccessDenied module={module} />;
  }
  return <Outlet />;
}

/** Envía al primer módulo permitido, no siempre a inventario. */
export function IndexRedirect() {
  const { user } = useAuth();
  if (user === null) {
    return <Navigate to="/login" replace />;
  }
  return <Navigate to={firstAccessiblePath(user)} replace />;
}
