import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

interface EmptyStateProps {
  icon: LucideIcon;
  title?: string;
  body: string;
  extra?: ReactNode;
  action?: ReactNode;
  testid?: string;
}

/** Composed empty state (DESIGN.md §4): icon + optional title + body + extra + action. */
export default function EmptyState({
  icon: Icon,
  title,
  body,
  extra,
  action,
  testid,
}: EmptyStateProps) {
  return (
    <div data-testid={testid} className="flex flex-col items-center px-2 py-6 text-center">
      <Icon className="h-10 w-10 text-muted" aria-hidden="true" />
      {title && <h2 className="mt-3 text-base font-semibold">{title}</h2>}
      <p className="mt-1 max-w-sm text-sm text-muted">{body}</p>
      {extra}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
