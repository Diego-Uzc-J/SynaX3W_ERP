interface ActiveSwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  hint: string;
}

/** Interruptor accesible (`role="switch"`) para el campo `is_active`. */
export default function ActiveSwitch({
  checked,
  onChange,
  label,
  hint,
}: ActiveSwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="flex w-full items-center justify-between gap-4 border border-concrete-200 bg-white px-3 py-2.5 text-left hover:border-ink-500"
    >
      <span>
        <span className="block text-sm font-medium text-ink-950">{label}</span>
        <span className="mt-0.5 block text-xs text-ink-500">{hint}</span>
      </span>
      <span
        aria-hidden="true"
        className={[
          "relative h-5 w-9 shrink-0 border transition-colors",
          checked
            ? "border-pine-600 bg-pine-600"
            : "border-concrete-400 bg-concrete-100",
        ].join(" ")}
      >
        <span
          className={[
            "absolute top-0.5 size-3.5 bg-white transition-transform",
            checked ? "translate-x-[18px]" : "translate-x-0.5",
          ].join(" ")}
        />
      </span>
    </button>
  );
}
