import type { JobStatus } from "../api/types";

const LABELS: Record<JobStatus, string> = {
  queued: "Chờ xử lý",
  running: "Đang xử lý",
  done: "Hoàn tất",
  failed: "Thất bại",
};

export default function StatusBadge({ job }: { job: { id: number; status: JobStatus } }) {
  return <span data-testid={`badge-${job.id}`}>{LABELS[job.status]}</span>;
}
