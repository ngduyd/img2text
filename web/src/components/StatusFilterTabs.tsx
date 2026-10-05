import type { JobListItem, JobStatus } from "../api/types";
import Button from "./ui/Button";

export type StatusFilter = "all" | JobStatus;

const TABS: { key: StatusFilter; label: string }[] = [
  { key: "all", label: "Tất cả" },
  { key: "queued", label: "Chờ xử lý" },
  { key: "running", label: "Đang xử lý" },
  { key: "done", label: "Hoàn tất" },
  { key: "failed", label: "Thất bại" },
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
    running: 0,
    done: 0,
    failed: 0,
  };
  for (const j of items) counts[j.status] += 1;

  return (
    <div className="mb-3 flex flex-wrap gap-1">
      {TABS.map(({ key, label }) => (
        <Button
          key={key}
          testid={`filter-${key}`}
          variant="ghost"
          size="sm"
          aria-pressed={value === key}
          className={value === key ? "bg-surface font-semibold" : undefined}
          onClick={() => onChange(key)}
        >
          {label} ({counts[key]})
        </Button>
      ))}
    </div>
  );
}
