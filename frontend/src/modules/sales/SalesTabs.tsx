import { NavLink } from "react-router-dom";

const TABS = [
  { to: "/sales/customers", label: "Clientes" },
  { to: "/sales/orders", label: "Pedidos y cotizaciones" },
  { to: "/sales/invoices", label: "Facturas" },
] as const;

/** Navegación secundaria común a las vistas del módulo de ventas. */
export default function SalesTabs() {
  return (
    <nav
      aria-label="Vistas de ventas"
      className="mt-6 flex overflow-x-auto border-b border-concrete-200"
    >
      {TABS.map((tab) => (
        <NavLink
          key={tab.to}
          to={tab.to}
          className={({ isActive }) =>
            [
              "-mb-px whitespace-nowrap border-b-2 px-4 py-2.5 text-sm font-semibold transition-colors",
              isActive
                ? "border-signal-500 text-ink-950"
                : "border-transparent text-ink-500 hover:border-concrete-400 hover:text-ink-950",
            ].join(" ")
          }
        >
          {tab.label}
        </NavLink>
      ))}
    </nav>
  );
}
