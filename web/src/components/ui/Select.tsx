import type { SelectHTMLAttributes } from "react";

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label: string;
  testid?: string;
}

/** Label-above select (DESIGN.md §3): h-10, rounded-sm, surface fill. */
export default function Select({ label, testid, id, className, ...rest }: SelectProps) {
  const selectId = id ?? testid;
  return (
    <div className="flex flex-col gap-1 text-sm">
      <label htmlFor={selectId} className="text-muted">
        {label}
      </label>
      <select
        id={selectId}
        data-testid={testid}
        className={`h-10 cursor-pointer rounded-sm border border-border bg-surface px-2 text-sm text-text focus-visible:outline-2 focus-visible:outline-accent ${className ?? ""}`}
        {...rest}
      />
    </div>
  );
}
