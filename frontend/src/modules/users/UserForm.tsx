import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import ActiveSwitch from "../../components/ActiveSwitch";
import FormSheet from "../../components/FormSheet";
import {
  useCreateUser,
  useResetUserPassword,
  useUpdateUser,
} from "../../api/users";
import type { AuthRole, AuthUser, RoleName } from "../../store/authStore";
import { ROLE_HINTS, ROLE_LABELS, ROLE_ORDER } from "./constants";

interface UserFormProps {
  open: boolean;
  /** `null` para crear; un usuario para editar. */
  user: AuthUser | null;
  roles: AuthRole[];
  onClose: () => void;
  onSaved: (user: AuthUser, mode: "created" | "updated") => void;
}

const labelClass = "mb-1.5 block text-xs font-semibold text-ink-700";
const fieldClass =
  "w-full border border-concrete-200 bg-white px-3 py-2 text-sm text-ink-950 " +
  "placeholder:text-concrete-400 focus:border-ink-950";
const hintClass = "mt-1 text-xs text-ink-500";

function passwordProblem(value: string): string | null {
  if (value.length < 10) {
    return "La contraseña debe tener al menos 10 caracteres.";
  }
  if (value.length > 128) {
    return "La contraseña no puede superar 128 caracteres.";
  }
  if (!/[A-Z]/.test(value)) {
    return "La contraseña debe incluir una mayúscula.";
  }
  if (!/[a-z]/.test(value)) {
    return "La contraseña debe incluir una minúscula.";
  }
  if (!/\d/.test(value)) {
    return "La contraseña debe incluir un número.";
  }
  if (!/[^A-Za-z0-9]/.test(value)) {
    return "La contraseña debe incluir un carácter especial.";
  }
  return null;
}

function sortedRoles(roles: AuthRole[]): AuthRole[] {
  return [...roles].sort(
    (left, right) =>
      ROLE_ORDER.indexOf(left.name) - ROLE_ORDER.indexOf(right.name),
  );
}

export default function UserForm({
  open,
  user,
  roles,
  onClose,
  onSaved,
}: UserFormProps) {
  const isEdit = user !== null;
  const orderedRoles = sortedRoles(roles);

  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [fullName, setFullName] = useState("");
  const [roleId, setRoleId] = useState("");
  const [password, setPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [formError, setFormError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const createMutation = useCreateUser();
  const updateMutation = useUpdateUser();
  const resetMutation = useResetUserPassword();
  const mutationError =
    createMutation.error ?? updateMutation.error ?? resetMutation.error;

  useEffect(() => {
    if (!open) {
      return;
    }
    setEmail(user?.email ?? "");
    setUsername(user?.username ?? "");
    setFullName(user?.full_name ?? "");
    setRoleId(user?.role.id ?? "");
    setPassword("");
    setNewPassword("");
    setIsActive(user === null ? true : user.is_active);
    setFormError(null);
    createMutation.reset();
    updateMutation.reset();
    resetMutation.reset();
    // `reset` es estable en TanStack Query; se omite de las dependencias.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, user]);

  const effectiveRoleId =
    roleId !== "" ? roleId : (orderedRoles[0]?.id ?? "");
  const selectedRole = orderedRoles.find(
    (role) => role.id === effectiveRoleId,
  );
  const roleUnavailable = orderedRoles.length === 0;

  function validate(): string | null {
    if (email.trim() === "") {
      return "El correo es obligatorio.";
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      return "Escribe un correo electrónico válido.";
    }
    if (username.trim() === "") {
      return "El nombre de usuario es obligatorio.";
    }
    if (!/^[A-Za-z0-9]{1,50}$/.test(username.trim())) {
      return "El usuario debe ser alfanumérico y tener entre 1 y 50 caracteres.";
    }
    if (fullName.trim() === "") {
      return "El nombre completo es obligatorio.";
    }
    if (fullName.trim().length > 150) {
      return "El nombre completo no puede superar 150 caracteres.";
    }
    if (effectiveRoleId === "") {
      return "Selecciona un rol para la cuenta.";
    }
    if (!isEdit) {
      const problem = passwordProblem(password);
      if (problem !== null) {
        return problem;
      }
    } else if (newPassword !== "") {
      const problem = passwordProblem(newPassword);
      if (problem !== null) {
        return `Nueva contraseña: ${problem}`;
      }
    }
    return null;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = validate();
    if (message !== null) {
      setFormError(message);
      return;
    }

    setFormError(null);
    setIsSubmitting(true);
    try {
      if (user === null) {
        const created = await createMutation.mutateAsync({
          email: email.trim(),
          username: username.trim(),
          full_name: fullName.trim(),
          password,
          role_id: effectiveRoleId,
        });
        onSaved(created, "created");
        return;
      }

      const updated = await updateMutation.mutateAsync({
        userId: user.id,
        payload: {
          email: email.trim(),
          username: username.trim(),
          full_name: fullName.trim(),
          role_id: effectiveRoleId,
          is_active: isActive,
        },
      });
      if (newPassword !== "") {
        await resetMutation.mutateAsync({
          userId: user.id,
          payload: { new_password: newPassword },
        });
      }
      onSaved(updated, "updated");
    } catch {
      // El mensaje queda en `mutationError`; la validación local ya se mostró.
    } finally {
      setIsSubmitting(false);
    }
  }

  const serverError =
    mutationError instanceof Error ? mutationError.message : null;
  const visibleError = formError ?? serverError;

  return (
    <FormSheet
      open={open}
      title={isEdit ? "Editar usuario" : "Nuevo usuario"}
      subtitle={
        isEdit
          ? `Actualiza la cuenta de ${user.full_name}.`
          : "Crea una cuenta y asígnale uno de los siete roles del ERP."
      }
      submitLabel={isEdit ? "Guardar cambios" : "Crear usuario"}
      pendingLabel="Guardando…"
      isPending={isSubmitting}
      onClose={onClose}
      onSubmit={handleSubmit}
    >
      <div>
        <label className={labelClass} htmlFor="user-full-name">
          Nombre completo <span className="text-signal-600">*</span>
        </label>
        <input
          id="user-full-name"
          // eslint-disable-next-line jsx-a11y/no-autofocus
          autoFocus
          className={fieldClass}
          type="text"
          maxLength={150}
          value={fullName}
          onChange={(event) => setFullName(event.currentTarget.value)}
          placeholder="María Fernanda Gómez"
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className={labelClass} htmlFor="user-email">
            Correo <span className="text-signal-600">*</span>
          </label>
          <input
            id="user-email"
            className={fieldClass}
            type="email"
            maxLength={255}
            autoComplete="off"
            value={email}
            onChange={(event) => setEmail(event.currentTarget.value)}
            placeholder="m.gomez@synapsisx.com"
          />
        </div>
        <div>
          <label className={labelClass} htmlFor="user-username">
            Usuario <span className="text-signal-600">*</span>
          </label>
          <input
            id="user-username"
            className={fieldClass}
            type="text"
            maxLength={50}
            autoComplete="off"
            value={username}
            onChange={(event) => setUsername(event.currentTarget.value)}
            placeholder="mgomez"
          />
          <p className={hintClass}>Solo letras y números.</p>
        </div>
      </div>

      <div>
        <label className={labelClass} htmlFor="user-role">
          Rol <span className="text-signal-600">*</span>
        </label>
        <select
          id="user-role"
          className={fieldClass}
          value={effectiveRoleId}
          disabled={roleUnavailable}
          onChange={(event) => setRoleId(event.currentTarget.value)}
        >
          {roleUnavailable ? (
            <option value="">
              {roles.length === 0 ? "Cargando roles…" : "Sin roles"}
            </option>
          ) : (
            orderedRoles.map((role) => (
              <option key={role.id} value={role.id}>
                {ROLE_LABELS[role.name as RoleName]}
              </option>
            ))
          )}
        </select>
        {selectedRole === undefined ? (
          <p className={hintClass}>
            No se pudo cargar el catálogo de roles.
          </p>
        ) : (
          <p className={hintClass}>
            {ROLE_HINTS[selectedRole.name]} Módulos:{" "}
            {selectedRole.allowed_modules.join(", ")}.
          </p>
        )}
      </div>

      {isEdit ? (
        <div>
          <label className={labelClass} htmlFor="user-new-password">
            Nueva contraseña{" "}
            <span className="font-normal text-ink-500">(opcional)</span>
          </label>
          <input
            id="user-new-password"
            className={fieldClass}
            type="password"
            autoComplete="new-password"
            maxLength={128}
            value={newPassword}
            onChange={(event) => setNewPassword(event.currentTarget.value)}
            placeholder="Déjala vacía para conservar la actual"
          />
          <p className={hintClass}>
            Al restablecerla se limpia cualquier bloqueo por intentos fallidos.
          </p>
        </div>
      ) : (
        <div>
          <label className={labelClass} htmlFor="user-password">
            Contraseña inicial <span className="text-signal-600">*</span>
          </label>
          <input
            id="user-password"
            className={fieldClass}
            type="password"
            autoComplete="new-password"
            maxLength={128}
            value={password}
            onChange={(event) => setPassword(event.currentTarget.value)}
            placeholder="Mínimo 10 caracteres"
          />
          <p className={hintClass}>
            Debe incluir mayúscula, minúscula, número y carácter especial. La
            cuenta se crea activa.
          </p>
        </div>
      )}

      {isEdit ? (
        <ActiveSwitch
          checked={isActive}
          onChange={setIsActive}
          label="Acceso habilitado"
          hint="Al desactivarlo, el token vigente deja de servir de inmediato."
        />
      ) : null}

      {visibleError === null ? null : (
        <p
          role="alert"
          className="border-l-2 border-signal-500 bg-signal-100 px-3 py-2 text-sm font-medium text-signal-600"
        >
          {visibleError}
        </p>
      )}
    </FormSheet>
  );
}
