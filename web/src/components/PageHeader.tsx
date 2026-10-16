import type { ReactNode } from "react";

export default function PageHeader({
  title,
  subtitle,
  actions,
  testid,
  beforeTitle,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  testid?: string;
  beforeTitle?: ReactNode;
}) {
  return (
    <header
      data-testid={testid}
      className="mb-6 flex flex-wrap items-end justify-between gap-4"
    >
      <div>
        {beforeTitle ? (
          <div className="flex items-center gap-3">
            {beforeTitle}
            <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
          </div>
        ) : (
          <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        )}
        {subtitle && <p className="mt-1 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}
