import {
  useCallback,
  useDeferredValue,
  useEffect,
  useState,
} from "react";

import { useRoles, useUpdateUser, useUsers } from "../../api/users";
import type { AuthUser, RoleName, UserFilters } from "../../api/users";
import { useAuth } from "../../store/authStore";
import { formatDate, initials, ROLE_LABELS, ROLE_ORDER } from "./constants";
import UserForm from "./UserForm";

const PAGE_SIZE = 15;

type StatusFilter = "all" | "active" | "inactive";
type RoleFilter = RoleName | "all";

function UserStatus({ isActive }: { isActive: boolean }) {
  if (!isActive) {
    return (
      <span className="inline-flex items-center gap-1.5 bg-concrete-100 px-2 py-1 text-xs font-semibold text-ink-500">
        <span className="size-1.5 bg-concrete-400" aria-hidden="true" />
        Inactivo
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 bg-pine-100 px-2 py-1 text-xs font-semibold text-pine-600">
      <span className="size-1.5 bg-pine-600" aria-hidden="true" />
      Activo
    </span>
  );
}

export default function UserList() {
  const { user: currentUser } = useAuth();

  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState<RoleFilter>("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [page, setPage] = useState(0);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<AuthUser | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);

  const deferredSearch = useDeferredValue(search.trim());
  const rolesQuery = useRoles();
  const updateMutation = useUpdateUser();

  const filters: UserFilters = {
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  };
  if (deferredSearch !== "") {
    filters.search = deferredSearch;
  }
  if (roleFilter !== "all") {
    filters.role = roleFilter;
  }
  if (statusFilter !== "all") {
    filters.is_active = statusFilter === "active";
  }

  const usersQuery = useUsers(filters);
  const users = usersQuery.data ?? [];
  const roles = rolesQuery.data ?? [];

  useEffect(() => {
    setPage(0);
  }, [deferredSearch, roleFilter, statusFilter]);

  const openCreate = useCallback(() => {
    setEditing(null);
    setFormOpen(true);
  }, []);

  const openEdit = useCallback((user: AuthUser) => {
    setEditing(user);
    setFormOpen(true);
  }, []);

  const closeForm = useCallback(() => setFormOpen(false), []);

  const handleSaved = useCallback(
    (saved: AuthUser, mode: "created" | "updated") => {
      setFeedback(
        mode === "created"
          ? `Usuario creado: ${saved.full_name} (${ROLE_LABELS[saved.role.name]}).`
          : `Usuario actualizado: ${saved.full_name}.`,
      );
      setFormOpen(false);
      setEditing(null);
    },
    [],
  );

  function toggleAccess(target: AuthUser) {
    setFeedback(null);
    updateMutation.mutate(
      { userId: target.id, payload: { is_active: !target.is_active } },
      {
        onSuccess: (updated) => {
          setFeedback(
            `${updated.full_name}: acceso ${
              updated.is_active ? "habilitado" : "deshabilitado"
            }.`,
          );
        },
      },
    );
  }

  const hasFilters =
    deferredSearch !== "" ||
    roleFilter !== "all" ||
    statusFilter !== "all";
  const activeOnPage = users.filter((user) => user.is_active).length;
  const queryError = usersQuery.error;
  const mutationError = updateMutation.error;

  function resetFilters() {
    setSearch("");
    setRoleFilter("all");
    setStatusFilter("all");
  }

  return (
    <div className="mx-auto w-full max-w-[1440px] px-4 pb-16 pt-8 sm:px-6 lg:px-10">
      <header className="flex flex-col gap-6 border-b-2 border-ink-950 pb-6 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-signal-600">
            Administración
          </p>
          <h1 className="mt-2 text-4xl font-extrabold tracking-tight sm:text-5xl">
            Usuarios
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-ink-700">
            Cuentas, roles y estado de acceso. Solo el rol administrador puede
            crear usuarios o cambiar sus permisos.
          </p>
        </div>
        <button
          type="button"
          onClick={openCreate}
          className="inline-flex shrink-0 items-center justify-center gap-2 bg-signal-500 px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-signal-600"
        >
          <span aria-hidden="true" className="text-lg leading-none">
            +
          </span>
          Nuevo usuario
        </button>
      </header>

      <dl className="mt-6 grid grid-cols-2 divide-x divide-concrete-200 border border-concrete-200 bg-white sm:grid-cols-3">
        <div className="px-4 py-3">
          <dt className="text-xs font-semibold text-ink-500">
            En esta página
          </dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums">
            {users.length}
          </dd>
        </div>
        <div className="px-4 py-3">
          <dt className="text-xs font-semibold text-ink-500">
            Activos visibles
          </dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums">
            {activeOnPage}
          </dd>
        </div>
        <div className="col-span-2 border-t border-concrete-200 px-4 py-3 sm:col-span-1 sm:border-t-0">
          <dt className="text-xs font-semibold text-ink-500">
            Roles del sistema
          </dt>
          <dd className="mt-1 text-2xl font-extrabold tabular-nums">
            {rolesQuery.isPending ? "—" : roles.length}
          </dd>
        </div>
      </dl>

      {feedback === null ? null : (
        <div
          role="status"
          className="mt-5 flex items-start justify-between gap-4 border border-pine-600/30 bg-pine-100 px-4 py-3 text-sm font-medium text-pine-600"
        >
          <p>{feedback}</p>
          <button
            type="button"
            onClick={() => setFeedback(null)}
            className="text-base leading-none text-pine-600 hover:text-ink-950"
            aria-label="Cerrar aviso"
          >
            ×
          </button>
        </div>
      )}

      {mutationError === null ? null : (
        <p
          role="alert"
          className="mt-5 border-l-2 border-signal-500 bg-signal-100 px-4 py-3 text-sm font-medium text-signal-600"
        >
          {mutationError.message}
        </p>
      )}

      <div className="flex flex-col gap-3 py-5 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex flex-1 flex-col gap-2 sm:flex-row">
          <div className="flex flex-1 border border-concrete-200 bg-white focus-within:border-ink-950">
            <label className="sr-only" htmlFor="user-search">
              Buscar usuarios
            </label>
            <input
              id="user-search"
              type="search"
              value={search}
              onChange={(event) => setSearch(event.currentTarget.value)}
              placeholder="Buscar por nombre, correo o usuario"
              className="min-w-0 flex-1 px-3 py-2 text-sm placeholder:text-concrete-400 focus:outline-none"
            />
          </div>

          <label className="sr-only" htmlFor="user-role-filter">
            Filtrar por rol
          </label>
          <select
            id="user-role-filter"
            value={roleFilter}
            onChange={(event) =>
              setRoleFilter(event.currentTarget.value as RoleFilter)
            }
            className="border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-700"
          >
            <option value="all">Todos los roles</option>
            {ROLE_ORDER.map((role) => (
              <option key={role} value={role}>
                {ROLE_LABELS[role]}
              </option>
            ))}
          </select>

          <label className="sr-only" htmlFor="user-status-filter">
            Filtrar por estado
          </label>
          <select
            id="user-status-filter"
            value={statusFilter}
            onChange={(event) =>
              setStatusFilter(event.currentTarget.value as StatusFilter)
            }
            className="border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-700"
          >
            <option value="all">Todos los estados</option>
            <option value="active">Solo activos</option>
            <option value="inactive">Solo inactivos</option>
          </select>
        </div>

        <p className="text-xs text-ink-500" aria-live="polite">
          {users.length} cuenta{users.length === 1 ? "" : "s"} en esta página
          {usersQuery.isFetching ? " · actualizando" : ""}
        </p>
      </div>

      {queryError !== null ? (
        <div className="border border-signal-500/40 bg-signal-100 px-5 py-6">
          <p className="text-sm font-semibold text-signal-600">
            No se pudo cargar la lista de usuarios.
          </p>
          <p className="mt-1 text-sm text-ink-700">{queryError.message}</p>
          <button
            type="button"
            onClick={() => void usersQuery.refetch()}
            className="mt-4 border border-signal-500 px-3 py-1.5 text-sm font-semibold text-signal-600 hover:bg-signal-500 hover:text-white"
          >
            Reintentar
          </button>
        </div>
      ) : usersQuery.isPending ? (
        <div className="border border-concrete-200 bg-white">
          {[0, 1, 2, 3, 4].map((row) => (
            <div
              key={row}
              className="flex items-center gap-6 border-b border-concrete-100 px-4 py-4 last:border-b-0"
            >
              <div className="size-9 animate-pulse bg-concrete-100" />
              <div className="h-4 w-1/3 animate-pulse bg-concrete-100" />
              <div className="h-4 w-1/5 animate-pulse bg-concrete-100" />
            </div>
          ))}
        </div>
      ) : users.length === 0 ? (
        <div className="border border-dashed border-concrete-200 bg-white px-6 py-16 text-center">
          <p className="text-lg font-semibold">
            {hasFilters
              ? "No hay usuarios que coincidan con los filtros."
              : "Todavía no hay cuentas registradas."}
          </p>
          <p className="mx-auto mt-2 max-w-sm text-sm text-ink-500">
            {hasFilters
              ? "Cambia la búsqueda, el rol o el estado para ver otras cuentas."
              : "Crea la primera cuenta y asígnale un rol del ERP."}
          </p>
          <button
            type="button"
            onClick={hasFilters ? resetFilters : openCreate}
            className="mt-5 border border-ink-950 px-4 py-2 text-sm font-semibold hover:bg-ink-950 hover:text-concrete-50"
          >
            {hasFilters ? "Limpiar filtros" : "Crear el primer usuario"}
          </button>
        </div>
      ) : (
        <div className="border border-concrete-200 bg-white">
          <div className="relative overflow-x-auto">
            <table className="w-full min-w-[920px] border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-concrete-200 text-xs font-semibold text-ink-500">
                  <th scope="col" className="px-4 py-3">
                    Cuenta
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Rol
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Estado
                  </th>
                  <th scope="col" className="px-4 py-3">
                    Alta
                  </th>
                  <th scope="col" className="px-4 py-3 text-right">
                    <span className="sr-only">Acciones</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => {
                  const isSelf = currentUser?.id === user.id;
                  const isToggling =
                    updateMutation.isPending &&
                    updateMutation.variables?.userId === user.id;
                  return (
                    <tr
                      key={user.id}
                      className="border-b border-concrete-100 last:border-b-0 hover:bg-concrete-50"
                    >
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-3">
                          <span
                            aria-hidden="true"
                            className="grid size-9 shrink-0 place-items-center bg-ink-950 text-xs font-bold text-concrete-50"
                          >
                            {initials(user.full_name)}
                          </span>
                          <div className="min-w-0">
                            <span className="block font-semibold text-ink-950">
                              {user.full_name}
                              {isSelf ? (
                                <span className="ml-2 bg-concrete-100 px-1.5 py-0.5 text-[0.6875rem] font-semibold text-ink-500">
                                  Tú
                                </span>
                              ) : null}
                            </span>
                            <span className="mt-0.5 block truncate text-xs text-ink-500">
                              {user.email}
                            </span>
                            <span className="block text-xs text-concrete-400">
                              @{user.username}
                            </span>
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className="block font-semibold text-ink-950">
                          {ROLE_LABELS[user.role.name]}
                        </span>
                        <span className="mt-0.5 block max-w-[15rem] text-xs text-ink-500">
                          {user.role.allowed_modules.length === 0
                            ? "Sin módulos"
                            : user.role.allowed_modules.join(", ")}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <UserStatus isActive={user.is_active} />
                      </td>
                      <td className="px-4 py-3 text-xs tabular-nums text-ink-500">
                        {formatDate(user.created_at)}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end gap-2">
                          <button
                            type="button"
                            onClick={() => openEdit(user)}
                            className="border border-concrete-200 px-2.5 py-1.5 text-xs font-semibold text-ink-700 hover:border-ink-950 hover:text-ink-950"
                          >
                            Editar
                          </button>
                          <button
                            type="button"
                            onClick={() => toggleAccess(user)}
                            disabled={isSelf || isToggling}
                            title={
                              isSelf
                                ? "No puedes desactivar tu propia cuenta."
                                : undefined
                            }
                            className={[
                              "border px-2.5 py-1.5 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-40",
                              user.is_active
                                ? "border-concrete-200 text-ink-700 hover:border-signal-500 hover:text-signal-600"
                                : "border-pine-600 text-pine-600 hover:bg-pine-100",
                            ].join(" ")}
                          >
                            {isToggling
                              ? "Guardando…"
                              : user.is_active
                                ? "Desactivar"
                                : "Activar"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <footer className="flex items-center justify-between gap-4 border-t border-concrete-200 px-4 py-3 text-sm">
            <p className="text-xs text-ink-500">
              Página {page + 1}
              {usersQuery.isFetching ? " · actualizando" : ""}
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={page === 0}
                onClick={() => setPage((current) => Math.max(0, current - 1))}
                className="border border-concrete-200 px-3 py-1.5 text-xs font-semibold text-ink-700 hover:border-ink-950 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Anterior
              </button>
              <button
                type="button"
                disabled={users.length < PAGE_SIZE}
                onClick={() => setPage((current) => current + 1)}
                className="border border-concrete-200 px-3 py-1.5 text-xs font-semibold text-ink-700 hover:border-ink-950 disabled:cursor-not-allowed disabled:opacity-40"
              >
                Siguiente
              </button>
            </div>
          </footer>
        </div>
      )}

      <UserForm
        open={formOpen}
        user={editing}
        roles={roles}
        onClose={closeForm}
        onSaved={handleSaved}
      />
    </div>
  );
}
