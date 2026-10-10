import type { JobListItem, JobStatus } from "../api/types";
import { STATUS_TEXT } from "../lib/status";
import Button from "./ui/Button";

export type StatusFilter = "all" | JobStatus;

// P2: chips share STATUS_TEXT spellings with badges (one spelling per status).
// "all" is a filter pseudo-status, not a job status — kept short.
const TABS: { key: StatusFilter; label: string }[] = [
  { key: "all", label: "Tất cả" },
  { key: "queued", label: STATUS_TEXT.queued },
  { key: "extracting", label: STATUS_TEXT.extracting },
  { key: "rendering", label: STATUS_TEXT.rendering },
  { key: "done", label: STATUS_TEXT.done },
  { key: "failed", label: STATUS_TEXT.failed },
];

/** Counts computed client-side from the loaded list; default "all". */
export default function StatusFilterTabs({
  items,
  value,
  onChange,
}: {
  items: JobListItem[];
  value: StatusFilter;
  onChange: (v: StatusFilter) => void;
}) {
  const counts: Record<StatusFilter, number> = {
    all: items.length,
    queued: 0,
    extracting: 0,
    rendering: 0,
    done: 0,
    failed: 0,
    // Hủy job: cancelled rows count under "all" only (no new chip).
    cancelled: 0,
  };
  for (const j of items) counts[j.status] += 1;

  return (
    <div className="flex flex-wrap gap-1">
      {TABS.map(({ key, label }) => (
        <Button
          key={key}
          testid={`filter-${key}`}
          variant="ghost"
          size="sm"
          aria-pressed={value === key}
          className={
            value === key
              ? "rounded-full border border-accent/40 bg-accent/10 font-semibold text-accent-text"
              : "rounded-full border border-transparent text-muted hover:bg-surface-2 hover:text-text"
          }
          onClick={() => onChange(key)}
        >
          {label} ({counts[key]})
        </Button>
      ))}
    </div>
  );
}
