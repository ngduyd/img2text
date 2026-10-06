import type { InputHTMLAttributes } from "react";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  testid?: string;
  error?: string;
  /** Helper text below the input (label-above pattern). Error text wins when both set. */
  helper?: string;
}

export default function Input({ label, testid, error, helper, className, id, ...rest }: InputProps) {
  const inputId = id ?? testid;
  const errorId = inputId ? `${inputId}-error` : undefined;
  const helperId = inputId ? `${inputId}-helper` : undefined;
  const describedBy = error ? errorId : helper ? helperId : undefined;
  return (
    <div className="flex flex-col gap-1 text-sm">
      <label className="flex flex-col gap-1" htmlFor={inputId}>
        <span className="text-muted">{label}</span>
        <input
          id={inputId}
          data-testid={testid}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          className={`h-10 rounded-sm border bg-surface px-3 text-text placeholder:text-muted ${
            error ? "border-error" : "border-border"
          } ${className ?? ""}`}
          {...rest}
        />
      </label>
      {helper && !error && (
        <span data-testid={helperId} className="text-sm text-muted">
          {helper}
        </span>
      )}
      {error && (
        <span data-testid={errorId} role="alert" className="text-sm text-error">
          {error}
        </span>
      )}
    </div>
  );
}
