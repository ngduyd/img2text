import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { api } from "../api/client";
import type { JobListItem } from "../api/types";
import { mapApiError } from "../lib/errors";
// Single spelling + tone per status (spec: shell, panels, badges share lib/status).
import { STATUS_TEXT, STATUS_TONE } from "../lib/status";
import Badge from "./ui/Badge";
import Button from "./ui/Button";

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
      className="flex flex-wrap items-center justify-between gap-3 px-4 py-3"
    >
      <div>
        <span className="font-medium text-text">
          <span className="font-mono">#{job.id}</span> · {job.file_type === "pdf" ? "PDF" : "Ảnh"} ·{" "}
          <span className="font-mono">{job.page_count}</span> trang
        </span>
        <div className="mt-0.5 text-xs text-muted">
          <span className="font-mono">{DATE_FORMAT.format(new Date(job.created_at))}</span>
          {duration && <span className="ml-2 font-mono">{duration}</span>}
        </div>
      </div>
      <div className="flex items-center gap-2">
        <Badge tone={STATUS_TONE[job.status]} testid={`badge-${job.id}`}>
          {STATUS_TEXT[job.status]}
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
