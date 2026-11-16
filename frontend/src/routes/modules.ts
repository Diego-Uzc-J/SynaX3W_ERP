import type { AuthUser } from "../store/authStore";
import { hasModuleAccess } from "../store/authStore";

export type ModuleKey =
  | "inventory"
  | "sales"
  | "purchasing"
  | "accounting"
  | "hr"
  | "manufacturing"
  | "users";

export interface ModuleDefinition {
  key: ModuleKey;
  label: string;
  description: string;
  path: string;
  /** `false` mientras solo exista la vista de preparación. */
  implemented: boolean;
}

/**
 * Orden canónico del menú. Inventario va primero para conservar el destino
 * inicial del ERP; Usuarios queda al final porque es administración.
 */
export const MODULES: readonly ModuleDefinition[] = [
  {
    key: "inventory",
    label: "Inventario",
    description: "Existencias, productos y bodegas",
    path: "/inventory",
    implemented: true,
  },
  {
    key: "sales",
    label: "Ventas",
    description: "Pedidos y facturación de venta",
    path: "/sales",
    implemented: false,
  },
  {
    key: "purchasing",
    label: "Compras",
    description: "Proveedores y órdenes de compra",
    path: "/purchasing",
    implemented: false,
  },
  {
    key: "accounting",
    label: "Contabilidad",
    description: "Facturación y libros contables",
    path: "/accounting",
    implemented: false,
  },
  {
    key: "hr",
    label: "Recursos humanos",
    description: "Personal y nómina",
    path: "/hr",
    implemented: false,
  },
  {
    key: "manufacturing",
    label: "Manufactura",
    description: "Órdenes y materias primas",
    path: "/manufacturing",
    implemented: false,
  },
  {
    key: "users",
    label: "Usuarios",
    description: "Cuentas, roles y accesos",
    path: "/users",
    implemented: true,
  },
] as const;

export const INVENTORY_LINKS = [
  {
    to: "/inventory",
    label: "Existencias",
    description: "Saldos por bodega",
  },
  {
    to: "/inventory/products",
    label: "Productos",
    description: "Catálogo de SKUs",
  },
  {
    to: "/inventory/warehouses",
    label: "Bodegas",
    description: "Almacenes físicos",
  },
] as const;

export function moduleByKey(key: ModuleKey): ModuleDefinition {
  const definition = MODULES.find((module) => module.key === key);
  if (definition === undefined) {
    throw new Error(`Módulo desconocido: ${key}`);
  }
  return definition;
}

/** Primer destino navegable según `allowed_modules`; nunca deja un callejón. */
export function firstAccessiblePath(user: AuthUser): string {
  const definition = MODULES.find((module) =>
    hasModuleAccess(user, module.key),
  );
  return definition?.path ?? "/sin-acceso";
}

/**
 * Destino seguro tras el login.
 *
 * Si la ruta guardada por la guardia pertenece a un módulo que el perfil no
 * puede ver (por ejemplo, un cierre de sesión desde `/users` seguido de un
 * login con rol de ventas), se ignora y se usa el primer módulo permitido.
 */
export function safeReturnPath(
  user: AuthUser,
  requestedPath: string | null,
): string {
  if (requestedPath === null) {
    return firstAccessiblePath(user);
  }
  const definition = MODULES.find(
    (module) =>
      requestedPath === module.path ||
      requestedPath.startsWith(`${module.path}/`),
  );
  if (definition !== undefined && hasModuleAccess(user, definition.key)) {
    return requestedPath;
  }
  return firstAccessiblePath(user);
}

/** Destinos que se muestran en el menú lateral para este perfil. */
export function accessibleModules(user: AuthUser): ModuleDefinition[] {
  return MODULES.filter((module) => hasModuleAccess(user, module.key));
}
