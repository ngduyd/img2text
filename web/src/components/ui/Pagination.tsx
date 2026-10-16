import type { ReactNode } from "react";
import Button from "./Button";

/** Windowed page numbers: luôn 1 + last + ±2 quanh current; gap > 1 → "…". */
export function pageWindow(current: number, total: number): (number | "…")[] {
  const nums = new Set<number>([1, total]);
  for (let n = current - 2; n <= current + 2; n++) if (n >= 1 && n <= total) nums.add(n);
  const sorted = [...nums].sort((a, b) => a - b);
  const out: (number | "…")[] = [];
  sorted.forEach((n, i) => {
    if (i > 0 && n - sorted[i - 1] > 1) out.push("…");
    out.push(n);
  });
  return out;
}

interface PaginationProps {
  page: number;
  totalPages: number;
  onChange: (page: number) => void;
  prevTestid?: string;
  nextTestid?: string;
  /** Prefix → page buttons get data-testid `${pageTestid}-${n}` (Jobs btn-page-*). */
  pageTestid?: string;
  numbers?: boolean;
  info?: ReactNode;
  navTestid?: string;
  ariaLabel?: string;
  prevLabel?: string;
  nextLabel?: string;
}

export default function Pagination({
  page,
  totalPages,
  onChange,
  prevTestid,
  nextTestid,
  pageTestid,
  numbers = false,
  info,
  navTestid,
  ariaLabel,
  prevLabel = "‹",
  nextLabel = "›",
}: PaginationProps) {
  return (
    <nav
      data-testid={navTestid}
      aria-label={ariaLabel}
      className="mt-4 flex flex-wrap items-center justify-center gap-2"
    >
      <Button
        testid={prevTestid}
        size="sm"
        variant="secondary"
        disabled={page <= 1}
        onClick={() => onChange(page - 1)}
      >
        {prevLabel}
      </Button>
      {numbers &&
        pageWindow(page, totalPages).map((n, i) =>
          typeof n === "number" ? (
            <Button
              key={n}
              testid={pageTestid ? `${pageTestid}-${n}` : undefined}
              size="sm"
              variant={n === page ? "primary" : "ghost"}
              aria-current={n === page ? "page" : undefined}
              onClick={() => onChange(n)}
            >
              {n}
            </Button>
          ) : (
            <span key={`gap-${i}`} aria-hidden="true" className="px-1 text-sm text-muted">
              …
            </span>
          ),
        )}
      <Button
        testid={nextTestid}
        size="sm"
        variant="secondary"
        disabled={page >= totalPages}
        onClick={() => onChange(page + 1)}
      >
        {nextLabel}
      </Button>
      {info}
    </nav>
  );
}
