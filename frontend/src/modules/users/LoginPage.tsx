import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { ApiError } from "../../api/client";
import { getMe, login, useCaptcha } from "../../api/users";
import { safeReturnPath } from "../../routes/modules";
import {
  clearSession,
  setTokens,
  setUser,
  useAuth,
} from "../../store/authStore";

const fieldClass =
  "w-full border border-concrete-200 bg-white px-3 py-2.5 text-sm text-ink-950 " +
  "placeholder:text-concrete-400 focus:border-ink-950";
const labelClass = "mb-1.5 block text-xs font-semibold text-ink-700";

/** Solo acepta rutas internas para evitar redirecciones abiertas. */
function destinationFromState(state: unknown): string | null {
  if (
    typeof state === "object" &&
    state !== null &&
    "from" in state &&
    typeof state.from === "string"
  ) {
    const from = state.from;
    if (from.startsWith("/") && !from.startsWith("//")) {
      return from;
    }
  }
  return null;
}

export default function LoginPage() {
  const auth = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const captchaQuery = useCaptcha();

  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [answer, setAnswer] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    document.title = "Acceso · SynapsisX ERP";
  }, []);

  // Cada desafío nuevo invalida la respuesta escrita para el anterior.
  useEffect(() => {
    setAnswer("");
  }, [captchaQuery.data?.captcha_token]);

  if (auth.user !== null && auth.accessToken !== null) {
    return (
      <Navigate
        to={safeReturnPath(
          auth.user,
          destinationFromState(location.state),
        )}
        replace
      />
    );
  }

  const captcha = captchaQuery.data;
  const captchaError =
    captchaQuery.error instanceof Error
      ? captchaQuery.error.message
      : captchaQuery.isError
        ? "No se pudo obtener el desafío de seguridad."
        : null;

  function refreshCaptcha() {
    setAnswer("");
    setFormError(null);
    void captchaQuery.refetch();
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);

    const normalizedIdentifier = identifier.trim();
    if (normalizedIdentifier === "") {
      setFormError("Escribe tu correo o nombre de usuario.");
      return;
    }
    if (password === "") {
      setFormError("Escribe tu contraseña.");
      return;
    }
    if (captcha === undefined) {
      setFormError("El desafío de seguridad aún no está listo.");
      return;
    }
    const normalizedAnswer = answer.trim();
    if (!/^\d+$/.test(normalizedAnswer)) {
      setFormError("Resuelve la suma con un número entero.");
      return;
    }

    setIsSubmitting(true);
    try {
      const session = await login({
        identifier: normalizedIdentifier,
        password,
        captcha_token: captcha.captcha_token,
        captcha_answer: Number(normalizedAnswer),
      });
      setTokens({
        accessToken: session.access_token,
        refreshToken: session.refresh_token,
      });
      const profile = await getMe();
      setUser(profile);
      navigate(
        safeReturnPath(profile, destinationFromState(location.state)),
        { replace: true },
      );
    } catch (error) {
      clearSession();
      setFormError(
        error instanceof Error
          ? error.message
          : "No se pudo iniciar sesión. Inténtalo de nuevo.",
      );
      if (error instanceof ApiError && error.status === 400) {
        setAnswer("");
      }
      if (
        error instanceof ApiError &&
        (error.status === 401 || error.status === 423)
      ) {
        setPassword("");
      }
      // Un 429 ya agotó el límite: no conviene pedir otro CAPTCHA todavía.
      if (!(error instanceof ApiError && error.status === 429)) {
        void captchaQuery.refetch();
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  const isBusy = isSubmitting || captchaQuery.isFetching;

  return (
    <div className="min-h-screen bg-concrete-50 text-ink-950 lg:grid lg:grid-cols-[minmax(0,1.08fr)_minmax(430px,0.92fr)]">
      <aside className="relative flex min-h-[320px] flex-col justify-between overflow-hidden bg-ink-950 px-6 py-8 text-concrete-50 sm:px-10 lg:min-h-screen lg:px-14 lg:py-12">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 opacity-[0.09]"
          style={{
            backgroundImage:
              "linear-gradient(to right, #f3f5ef 1px, transparent 1px), linear-gradient(to bottom, #f3f5ef 1px, transparent 1px)",
            backgroundSize: "56px 56px",
          }}
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -right-20 top-24 size-72 border border-concrete-50/20"
        />

        <div className="relative flex items-center gap-3">
          <span className="grid size-10 place-items-center bg-signal-500 text-base font-extrabold tracking-tight text-white">
            SX
          </span>
          <div>
            <p className="text-sm font-semibold">SynapsisX</p>
            <p className="text-xs text-concrete-400">ERP modular</p>
          </div>
        </div>

        <div className="relative mt-16 max-w-2xl lg:mt-0">
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-signal-500">
            Control de acceso
          </p>
          <h1 className="mt-5 max-w-xl text-5xl font-extrabold leading-[0.95] tracking-tight sm:text-6xl lg:text-7xl">
            La operación empieza con una identidad verificada.
          </h1>
          <p className="mt-6 max-w-lg text-sm leading-relaxed text-concrete-400 sm:text-base">
            Un único punto de entrada para inventario, ventas, compras,
            contabilidad, personal y manufactura. Cada rol ve solo lo que
            necesita.
          </p>

          <ol className="mt-10 divide-y divide-white/10 border-y border-white/10">
            {[
              ["01", "CAPTCHA aritmético", "Firma HMAC con vigencia de 3 minutos."],
              ["02", "Credenciales", "Hash Argon2id y respuesta uniforme ante errores."],
              ["03", "Sesión", "Access token de 30 minutos y refresh de 7 días."],
            ].map(([step, title, description]) => (
              <li
                key={step}
                className="grid grid-cols-[2.5rem_1fr] gap-3 py-4 sm:grid-cols-[3rem_1fr]"
              >
                <span className="pt-0.5 text-xs font-semibold tabular-nums text-signal-500">
                  {step}
                </span>
                <span>
                  <span className="block text-sm font-semibold text-concrete-50">
                    {title}
                  </span>
                  <span className="mt-0.5 block text-xs leading-relaxed text-concrete-400">
                    {description}
                  </span>
                </span>
              </li>
            ))}
          </ol>
        </div>

        <div className="relative mt-10 flex flex-wrap gap-x-6 gap-y-2 text-xs text-concrete-400 lg:mt-0">
          <span>Máximo 5 intentos por minuto</span>
          <span aria-hidden="true" className="hidden sm:inline">
            /
          </span>
          <span>Bloqueo temporal tras 5 fallos</span>
        </div>
      </aside>

      <main className="flex items-center justify-center px-4 py-10 sm:px-8 lg:px-10 lg:py-14">
        <div className="w-full max-w-md">
          <div className="border-t-4 border-signal-500 bg-white p-6 shadow-[12px_12px_0_0_rgba(20,25,20,0.06)] sm:p-8">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-ink-500">
              Sesión corporativa
            </p>
            <h2 className="mt-2 text-3xl font-extrabold tracking-tight">
              Iniciar sesión
            </h2>
            <p className="mt-2 text-sm leading-relaxed text-ink-500">
              Usa tu correo o nombre de usuario. El desafío confirma que la
              petición viene de una persona.
            </p>

            <form className="mt-7 space-y-5" onSubmit={handleSubmit} noValidate>
              <div>
                <label className={labelClass} htmlFor="login-identifier">
                  Correo o usuario
                </label>
                <input
                  id="login-identifier"
                  className={fieldClass}
                  type="text"
                  autoComplete="username"
                  // eslint-disable-next-line jsx-a11y/no-autofocus
                  autoFocus
                  value={identifier}
                  onChange={(event) => setIdentifier(event.currentTarget.value)}
                  placeholder="admin@synapsisx.com"
                />
              </div>

              <div>
                <label className={labelClass} htmlFor="login-password">
                  Contraseña
                </label>
                <div className="flex border border-concrete-200 bg-white focus-within:border-ink-950">
                  <input
                    id="login-password"
                    className="min-w-0 flex-1 px-3 py-2.5 text-sm text-ink-950 placeholder:text-concrete-400 focus:outline-none"
                    type={showPassword ? "text" : "password"}
                    autoComplete="current-password"
                    maxLength={128}
                    value={password}
                    onChange={(event) =>
                      setPassword(event.currentTarget.value)
                    }
                    placeholder="Tu contraseña"
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((current) => !current)}
                    className="border-l border-concrete-200 px-3 text-xs font-semibold text-ink-500 hover:text-ink-950"
                    aria-label={
                      showPassword
                        ? "Ocultar contraseña"
                        : "Mostrar contraseña"
                    }
                  >
                    {showPassword ? "Ocultar" : "Ver"}
                  </button>
                </div>
              </div>

              <div className="border border-concrete-200 bg-concrete-50 p-3.5">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-[0.16em] text-ink-500">
                      Verificación aritmética
                    </p>
                    <p
                      className="mt-1.5 text-lg font-bold tabular-nums text-ink-950"
                      aria-live="polite"
                    >
                      {captcha?.question ??
                        (captchaQuery.isPending
                          ? "Generando desafío…"
                          : "Desafío no disponible")}
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={refreshCaptcha}
                    disabled={captchaQuery.isFetching}
                    className="shrink-0 border border-concrete-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-ink-700 hover:border-ink-950 hover:text-ink-950 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {captchaQuery.isFetching ? "…" : "Nuevo"}
                  </button>
                </div>

                <label className={labelClass} htmlFor="login-captcha-answer">
                  Resultado
                </label>
                <input
                  id="login-captcha-answer"
                  className={fieldClass}
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]*"
                  autoComplete="off"
                  value={answer}
                  onChange={(event) => setAnswer(event.currentTarget.value)}
                  placeholder="Escribe la suma"
                  aria-describedby="login-captcha-hint"
                />
                <p
                  id="login-captcha-hint"
                  className="mt-1.5 text-xs text-ink-500"
                >
                  El desafío caduca a los 3 minutos. Si falla, se genera uno
                  nuevo.
                </p>
              </div>

              {captchaError === null ? null : (
                <div
                  role="alert"
                  className="flex items-start justify-between gap-3 border-l-2 border-clay-600 bg-clay-100 px-3 py-2 text-sm text-clay-600"
                >
                  <p>{captchaError}</p>
                  <button
                    type="button"
                    onClick={refreshCaptcha}
                    className="shrink-0 text-xs font-semibold underline"
                  >
                    Reintentar
                  </button>
                </div>
              )}

              {formError === null ? null : (
                <p
                  role="alert"
                  className="border-l-2 border-signal-500 bg-signal-100 px-3 py-2 text-sm font-medium text-signal-600"
                >
                  {formError}
                </p>
              )}

              <button
                type="submit"
                disabled={isBusy || captcha === undefined}
                className="w-full bg-signal-500 px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-signal-600 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {isSubmitting ? "Verificando…" : "Entrar al ERP"}
              </button>
            </form>
          </div>

          <p className="mt-4 flex items-center justify-between gap-3 text-xs text-ink-500">
            <span>Acceso restringido a personal autorizado.</span>
            <span className="tabular-nums">v0.1</span>
          </p>
        </div>
      </main>
    </div>
  );
}
