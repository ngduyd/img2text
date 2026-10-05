import type { ButtonHTMLAttributes } from "react";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md";

const BASE =
  "inline-flex cursor-pointer items-center justify-center gap-2 rounded-lg font-medium transition-opacity disabled:cursor-not-allowed disabled:opacity-50";

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-accent text-white hover:opacity-90",
  secondary: "border border-border bg-surface text-text hover:bg-border/30",
  ghost: "text-text hover:bg-surface",
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
