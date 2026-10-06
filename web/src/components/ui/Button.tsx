import type { ButtonHTMLAttributes } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md";

const BASE =
  "inline-flex cursor-pointer items-center justify-center gap-2 rounded-md font-medium transition duration-150 ease-out active:-translate-y-px active:brightness-110 disabled:cursor-not-allowed disabled:opacity-50";

/* secondary = outline role (bordered, non-accent). No glow, no ring on rest. */
const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-accent text-accent-contrast hover:opacity-90",
  secondary: "border border-border bg-surface text-text hover:bg-surface-2",
  ghost: "text-text hover:bg-surface-2",
  danger: "text-error hover:bg-error/10",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "px-3 py-1 text-sm",
  md: "px-4 py-2 text-base",
};

/** Shared class builder — nav Links (btn-login/btn-profile) style like Buttons. */
export function buttonClasses(variant: ButtonVariant = "primary", size: ButtonSize = "md"): string {
  return [BASE, VARIANTS[variant], SIZES[size]].join(" ");
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  testid?: string;
}

export default function Button({
  variant = "primary",
  size = "md",
  loading = false,
  testid,
  className,
  children,
  disabled,
  type,
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type ?? "button"}
      data-testid={testid}
      data-variant={variant}
      data-size={size}
      aria-busy={loading || undefined}
      disabled={disabled || loading}
      className={[buttonClasses(variant, size), className].filter(Boolean).join(" ")}
      {...rest}
    >
      {children}
    </button>
  );
}
