import { Link } from "react-router-dom";

import { ROLE_LABELS } from "../modules/users/constants";
import { useAuth } from "../store/authStore";
import type { ModuleKey } from "./modules";
import { firstAccessiblePath, moduleByKey } from "./modules";

/**
 * Destino neutro para módulos cuyo router aún no existe.
 *
 * La ruta ya pasó por `RequireModule`, así que solo llegan perfiles con el
 * permiso correspondiente en `allowed_modules`.
 */
export default function ModulePlaceholder({
  module,
}: {
  module: ModuleKey;
}) {
  const { user } = useAuth();
  const definition = moduleByKey(module);

  if (user === null) {
    return null;
  }

  const home = firstAccessiblePath(user);
  const showHomeLink = home !== definition.path;

  return (
    <div className="mx-auto w-full max-w-[1100px] px-4 pb-16 pt-10 sm:px-6 lg:px-10">
      <header className="border-b-2 border-ink-950 pb-6">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-signal-600">
          Módulo habilitado
        </p>
        <h1 className="mt-2 text-4xl font-extrabold tracking-tight sm:text-5xl">
          {definition.label}
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-700">
          {definition.description}. Tu rol{" "}
          <strong>{ROLE_LABELS[user.role.name]}</strong> tiene permiso para este
          módulo, pero su interfaz operativa todavía no está implementada.
        </p>
      </header>

      <div className="mt-8 grid gap-4 border border-concrete-200 bg-white p-6 sm:grid-cols-[1fr_auto] sm:items-center">
        <div>
          <p className="text-sm font-semibold">Ruta protegida y lista</p>
          <p className="mt-1 text-sm text-ink-500">
            La guardia ya valida <code>allowed_modules</code> y la API aplica
            el mismo control. Cuando exista el router de {definition.label.toLowerCase()},
            esta vista se sustituye por su pantalla real.
          </p>
        </div>
        {showHomeLink ? (
          <Link
            to={home}
            className="inline-flex shrink-0 border border-ink-950 px-4 py-2 text-sm font-semibold hover:bg-ink-950 hover:text-concrete-50"
          >
            Volver a mi módulo
          </Link>
        ) : null}
      </div>
    </div>
  );
}
