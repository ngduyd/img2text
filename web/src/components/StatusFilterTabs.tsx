import type { JobListItem, JobStatus } from "../api/types";
import { STATUS_KEY } from "../lib/status";
import { useT } from "../i18n";
import Button from "./ui/Button";

export type StatusFilter = "all" | JobStatus;

// P2: chips share STATUS_KEY spellings with badges (one spelling per status).
// "all" is a filter pseudo-status, not a job status — kept short.
const TAB_KEYS: { key: StatusFilter; labelKey: string }[] = [
  { key: "all", labelKey: "jobs.filter.all" },
  { key: "queued", labelKey: STATUS_KEY.queued },
  { key: "extracting", labelKey: STATUS_KEY.extracting },
  { key: "rendering", labelKey: STATUS_KEY.rendering },
  { key: "done", labelKey: STATUS_KEY.done },
  { key: "failed", labelKey: STATUS_KEY.failed },
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
  const { t } = useT();
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
    // Mobile: 6 chip cuộn ngang (không đẩy nút upload khỏi fold); md+ wrap.
    <div className="flex gap-1 overflow-x-auto whitespace-nowrap [&>*]:shrink-0 md:flex-wrap md:overflow-visible">
      {TAB_KEYS.map(({ key, labelKey }) => (
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
          {t(labelKey)} ({counts[key]})
        </Button>
      ))}
    </div>
  );
}
