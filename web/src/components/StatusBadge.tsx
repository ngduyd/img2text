import type { Job } from "../api/types";

const LABELS: Record<Job["status"], string> = {
  queued: "Chờ xử lý",
  running: "Đang xử lý",
  done: "Hoàn tất",
  failed: "Thất bại",
};

export default function StatusBadge({ job }: { job: Job }) {
  return <span data-testid={`badge-${job.id}`}>{LABELS[job.status]}</span>;
}
