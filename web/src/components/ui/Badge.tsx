import type { ReactNode } from "react";

export type BadgeTone = "neutral" | "success" | "warning" | "error" | "info";

const TONES: Record<BadgeTone, string> = {
  neutral: "border-border bg-surface text-muted",
  success: "border-success/40 bg-success/10 text-success",
  warning: "border-warning/40 bg-warning/10 text-warning",
  error: "border-error/40 bg-error/10 text-error",
  info: "border-accent/40 bg-accent/10 text-accent",
};

export default function Badge({
  tone = "neutral",
  children,
  testid,
}: {
  tone?: BadgeTone;
  children: ReactNode;
  testid?: string;
}) {
  return (
    <span
      data-testid={testid}
      data-tone={tone}
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${TONES[tone]}`}
    >
      {children}
    </span>
  );
}
