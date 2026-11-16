import { NavLink, Outlet } from "react-router-dom";

const NAV_ITEMS = [
  {
    to: "/inventory",
    label: "Existencias",
    description: "Saldos y movimientos",
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

export default function AppLayout() {
  return (
    <div className="min-h-screen bg-concrete-50 text-ink-950 md:flex">
      <aside className="sticky top-0 hidden h-screen w-20 shrink-0 flex-col justify-between bg-ink-950 px-3 py-6 md:flex lg:w-60 lg:px-5">
        <div>
          <div className="mb-10 flex items-center gap-3">
            <span className="grid size-10 shrink-0 place-items-center bg-signal-500 text-base font-extrabold tracking-tight text-white">
              SX
            </span>
            <div className="hidden lg:block">
              <p className="text-sm font-semibold text-concrete-50">SynapsisX</p>
              <p className="text-xs text-concrete-400">ERP modular</p>
            </div>
          </div>

          <p className="mb-2 hidden px-3 text-xs font-semibold uppercase tracking-[0.18em] text-concrete-400 lg:block">
            Inventario
          </p>

          <nav aria-label="Navegación principal" className="space-y-1">
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end
                className={({ isActive }) =>
                  [
                    "block border-l-2 px-3 py-2.5 transition-colors",
                    isActive
                      ? "border-signal-500 bg-white/5 text-concrete-50"
                      : "border-transparent text-concrete-400 hover:border-concrete-400 hover:text-concrete-50",
                  ].join(" ")
                }
              >
                <span className="block text-sm font-semibold lg:text-[0.8125rem]">
                  {item.label}
                </span>
                <span className="hidden text-xs text-concrete-400 lg:block">
                  {item.description}
                </span>
              </NavLink>
            ))}
          </nav>
        </div>

        <p className="hidden text-xs leading-relaxed text-concrete-400 lg:block">
          Operaciones
          <br />
          v0.1 · Monolito modular
        </p>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-4 border-b border-concrete-200 px-4 py-3 md:hidden">
          <div className="flex shrink-0 items-center gap-2.5">
            <span className="grid size-8 place-items-center bg-signal-500 text-xs font-extrabold tracking-tight text-white">
              SX
            </span>
            <span className="text-sm font-semibold">SynapsisX ERP</span>
          </div>
          <nav
            aria-label="Navegación principal"
            className="flex min-w-0 items-center gap-4 overflow-x-auto"
          >
            {NAV_ITEMS.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end
                className={({ isActive }) =>
                  [
                    "whitespace-nowrap border-b-2 pb-0.5 text-sm font-semibold transition-colors",
                    isActive
                      ? "border-signal-500 text-ink-950"
                      : "border-transparent text-ink-500 hover:text-ink-950",
                  ].join(" ")
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </header>

        <main className="min-w-0 flex-1">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
