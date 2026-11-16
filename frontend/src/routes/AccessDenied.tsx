import { Link } from "react-router-dom";

import { ROLE_LABELS } from "../modules/users/constants";
import { useAuth } from "../store/authStore";
import type { ModuleKey } from "./modules";
import { firstAccessiblePath, MODULES, moduleByKey } from "./modules";

function describePermission(permission: string): string {
  const [base, scope] = permission.split(":", 2);
  const definition = MODULES.find((module) => module.key === base);
  if (definition === undefined) {
    return permission;
  }
  return scope === "read" ? `${definition.label} (lectura)` : definition.label;
}

/** Vista 403 para una ruta válida pero fuera de `allowed_modules`. */
export default function AccessDenied({
  module,
}: {
  module: ModuleKey | null;
}) {
  const { user } = useAuth();
  const definition = module === null ? null : moduleByKey(module);
  const moduleLabel = definition?.label ?? "Este módulo";

  if (user === null) {
    return null;
  }

  return (
    <div className="mx-auto w-full max-w-[1100px] px-4 pb-16 pt-10 sm:px-6 lg:px-10">
      <div className="relative overflow-hidden border border-concrete-200 bg-white px-6 py-12 sm:px-10 sm:py-16">
        <p
          aria-hidden="true"
          className="pointer-events-none absolute -right-4 -top-10 text-[10rem] font-extrabold leading-none tracking-tighter text-concrete-100 sm:text-[14rem]"
        >
          403
        </p>
        <div className="relative max-w-2xl">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-signal-600">
            Acceso restringido
          </p>
          <h1 className="mt-3 text-4xl font-extrabold tracking-tight sm:text-5xl">
            {definition === null
              ? "Tu cuenta no tiene módulos asignados."
              : `${moduleLabel} no está en tu ruta.`}
          </h1>
          <p className="mt-4 text-sm leading-relaxed text-ink-700">
            Tu rol <strong>{ROLE_LABELS[user.role.name]}</strong> no incluye{" "}
            {definition === null
              ? "ningún módulo operativo"
              : `el módulo de ${moduleLabel.toLowerCase()}`}
            . La API también rechaza estas peticiones con 403, así que la
            restricción no es solo visual.
          </p>

          <div className="mt-7 border border-concrete-200 bg-concrete-50 px-4 py-3">
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-ink-500">
              Módulos habilitados
            </p>
            <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-ink-700">
              {user.role.allowed_modules.length === 0 ? (
                <li>Sin módulos asignados</li>
              ) : (
                user.role.allowed_modules.map((permission) => (
                  <li key={permission}>
                    {describePermission(permission)}
                  </li>
                ))
              )}
            </ul>
          </div>

          <Link
            to={firstAccessiblePath(user)}
            className="mt-7 inline-flex bg-ink-950 px-4 py-2.5 text-sm font-semibold text-concrete-50 hover:bg-ink-900"
          >
            Ir a mi primer módulo
          </Link>
        </div>
      </div>
    </div>
  );
}
