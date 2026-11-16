interface StatusBadgeProps {
  isActive: boolean;
  isLow: boolean;
}

/** Estado de un producto: inactivo, bajo mínimo o disponible. */
export default function StatusBadge({ isActive, isLow }: StatusBadgeProps) {
  if (!isActive) {
    return (
      <span className="inline-flex items-center gap-1.5 bg-concrete-100 px-2 py-1 text-xs font-semibold text-ink-500">
        <span className="size-1.5 bg-concrete-400" aria-hidden="true" />
        Inactivo
      </span>
    );
  }
  if (isLow) {
    return (
      <span className="inline-flex items-center gap-1.5 bg-clay-100 px-2 py-1 text-xs font-semibold text-clay-600">
        <span className="size-1.5 bg-clay-600" aria-hidden="true" />
        Bajo mínimo
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 bg-pine-100 px-2 py-1 text-xs font-semibold text-pine-600">
      <span className="size-1.5 bg-pine-600" aria-hidden="true" />
      Disponible
    </span>
  );
}
