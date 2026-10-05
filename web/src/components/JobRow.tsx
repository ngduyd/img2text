import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { api } from "../api/client";
import type { JobListItem, JobStatus } from "../api/types";
import { mapApiError } from "../lib/errors";
import Badge from "./ui/Badge";
import type { BadgeTone } from "./ui/Badge";
import Button from "./ui/Button";

const STATUS_LABELS: Record<JobStatus, string> = {
  queued: "Chờ xử lý",
  running: "Đang xử lý",
  done: "Hoàn tất",
  failed: "Thất bại",
};

/** VERDICT-style tone map (lib/verdicts.ts pattern). */
const STATUS_TONES: Record<JobStatus, BadgeTone> = {
  queued: "neutral",
  running: "info",
  done: "success",
  failed: "error",
};

const DATE_FORMAT = new Intl.DateTimeFormat("vi-VN", { dateStyle: "medium", timeStyle: "short" });

function formatDuration(ms: number): string {
  const s = Math.round(ms / 1000);
  return s < 60 ? `${s} giây` : `${Math.round(s / 60)} phút`;
}

/** File-centric list row (R52): server list has NO storage_key → name line from id/type/pages. */
export default function JobRow({ job }: { job: JobListItem }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const retry = useMutation({
    mutationFn: () => api.retryJob(job.id),
    onSuccess: () => {
      toast.success("Đã chạy lại.");
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (err) => toast.error(mapApiError(err)),
  });
  // Duration only when both timestamps present — server list omits them today (R52).
  const doneOrFailed = job.status === "done" || job.status === "failed";
  const duration =
    doneOrFailed && job.started_at && job.finished_at
      ? formatDuration(new Date(job.finished_at).getTime() - new Date(job.started_at).getTime())
      : null;

  return (
    <li
      data-testid={`job-row-${job.id}`}
      className="flex flex-wrap items-center justify-between gap-2 px-4 py-3"
    >
      <div>
        <span>
          #{job.id} · {job.file_type === "pdf" ? "PDF" : "Ảnh"} · {job.page_count} trang
        </span>
        <div className="text-xs text-muted">
          {DATE_FORMAT.format(new Date(job.created_at))}
          {duration && <span className="ml-2">{duration}</span>}
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Badge tone={STATUS_TONES[job.status]} testid={`badge-${job.id}`}>
          {STATUS_LABELS[job.status]}
        </Badge>
        <Button
          testid={`btn-view-${job.id}`}
          size="sm"
          variant="secondary"
          onClick={() => navigate(`/jobs/${job.id}`)}
        >
          Xem
        </Button>
        {job.status === "done" && (
          <Button
            testid={`btn-dl-original-${job.id}`}
            size="sm"
            variant="secondary"
            onClick={async () => {
              // R59a: download failure surfaces as toast (no inline slot here).
              try {
                const { url } = await api.getJobFile(job.id);
                window.open(url, "_blank");
              } catch (err) {
                toast.error(mapApiError(err));
              }
            }}
          >
            Tải bản gốc
          </Button>
        )}
        {job.status === "failed" && (
          <Button
            testid={`btn-retry-${job.id}`}
            size="sm"
            variant="secondary"
            disabled={retry.isPending}
            onClick={() => retry.mutate()}
          >
            Chạy lại
          </Button>
        )}
      </div>
    </li>
  );
}
