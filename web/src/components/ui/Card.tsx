import type { ReactNode } from "react";

export default function Card({
  title,
  testid,
  children,
  actions,
  bare = false,
}: {
  title?: string;
  testid?: string;
  children: ReactNode;
  actions?: ReactNode;
  /** Đã nằm trong một card khác → chỉ render nội dung (không viền/nền/tiêu đề). */
  bare?: boolean;
}) {
  if (bare) return <div data-testid={testid}>{children}</div>;
  return (
    <section data-testid={testid} className="rounded-card border border-border bg-surface p-4 shadow-card">
      {(title || actions) && (
        <header className="mb-3 flex items-center justify-between gap-3">
          {title && <h2 className="text-lg font-semibold">{title}</h2>}
          {actions && <div className="flex gap-2">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}
