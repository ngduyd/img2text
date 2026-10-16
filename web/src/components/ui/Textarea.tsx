import type { TextareaHTMLAttributes } from "react";

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label: string;
  testid?: string;
  error?: string;
}

/** Label-above textarea mirroring Input (error → role=alert). */
export default function Textarea({ label, testid, error, id, className, ...rest }: TextareaProps) {
  const taId = id ?? testid;
  const errorId = taId ? `${taId}-error` : undefined;
  return (
    <div className="flex flex-col gap-1 text-sm">
      <label className="flex flex-col gap-1" htmlFor={taId}>
        <span className="text-muted">{label}</span>
        <textarea
          id={taId}
          data-testid={testid}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? errorId : undefined}
          className={`rounded-sm border bg-surface px-3 py-2 text-text placeholder:text-muted ${
            error ? "border-error" : "border-border"
          } ${className ?? ""}`}
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
