import { NavLink } from "react-router-dom";

const TABS = [
  { to: "/inventory", label: "Existencias" },
  { to: "/inventory/products", label: "Productos" },
  { to: "/inventory/warehouses", label: "Bodegas" },
] as const;

/** Navegación secundaria común a las tres vistas del módulo. */
export default function InventoryTabs() {
  return (
    <nav
      aria-label="Vistas de inventario"
      className="mt-6 flex overflow-x-auto border-b border-concrete-200"
    >
      {TABS.map((tab) => (
        <NavLink
          key={tab.to}
          to={tab.to}
          end
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
