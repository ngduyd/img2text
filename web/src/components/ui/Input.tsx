import type { InputHTMLAttributes } from "react";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  testid?: string;
  error?: string;
}

export default function Input({ label, testid, error, className, id, ...rest }: InputProps) {
  const inputId = id ?? testid;
  const errorId = inputId ? `${inputId}-error` : undefined;
  return (
    <div className="flex flex-col gap-1 text-sm">
      <label className="flex flex-col gap-1" htmlFor={inputId}>
        <span className="text-muted">{label}</span>
        <input
          id={inputId}
          data-testid={testid}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
          className={`rounded-lg border border-border bg-surface px-3 py-2 text-text placeholder:text-muted ${className ?? ""}`}
          {...rest}
        />
      </label>
      {error && (
        <span data-testid={errorId} role="alert" className="text-sm text-error">
          {error}
        </span>
      )}
    </div>
  );
}
