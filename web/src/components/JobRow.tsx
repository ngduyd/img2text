import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Download, FileText, Image as ImageIcon, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { api } from "../api/client";
import type { JobListItem } from "../api/types";
import { mapApiError } from "../lib/errors";
// Single spelling + tone per status (spec: shell, panels, badges share lib/status).
import { STATUS_TEXT, STATUS_TONE, PENDING_STATUSES } from "../lib/status";
import Badge from "./ui/Badge";
import Button from "./ui/Button";
import ConfirmDialog from "./ConfirmDialog";

const DATE_FORMAT = new Intl.DateTimeFormat("vi-VN", { dateStyle: "medium", timeStyle: "short" });

function formatDuration(ms: number): string {
  const s = Math.round(ms / 1000);
  return s < 60 ? `${s} giây` : `${Math.round(s / 60)} phút`;
}

/** File-centric list row (R52): server list has NO storage_key → name line from id/type/pages.
 *  Phase 4: `selected`/`onToggle` add the bulk-retry checkbox (no handler → no checkbox).
 */
export default function JobRow({
  job,
  selected = false,
  onToggle,
}: {
  job: JobListItem;
  selected?: boolean;
  onToggle?: (id: number) => void;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const retry = useMutation({
    mutationFn: () => api.retryJob(job.id),
    onSuccess: () => {
      // Plan job-phases R59: retry upsert lịch chạy lại.
      toast.success("Đã lên lịch chạy lại");
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (err) => toast.error(mapApiError(err)),
  });
  const cancel = useMutation({
    mutationFn: () => api.cancelJob(job.id),
    onSuccess: () => {
      toast.success("Đã hủy job");
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (err) => toast.error(mapApiError(err)),
  });
  const deleteJob = useMutation({
    mutationFn: () => api.deleteJob(job.id),
    onSuccess: () => {
      toast.success("Đã xóa job");
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (err) => toast.error(mapApiError(err)),
  });
  const [confirmDelete, setConfirmDelete] = useState(false);
  // Hủy job: pending bucket (queued|extracting|rendering) — lib/status single spelling.
  const cancellable = PENDING_STATUSES.includes(job.status);
  // Duration only when both timestamps present — server list omits them today (R52).
  const doneOrFailed = job.status === "done" || job.status === "failed";
  const duration =
    doneOrFailed && job.started_at && job.finished_at
      ? formatDuration(new Date(job.finished_at).getTime() - new Date(job.started_at).getTime())
      : null;
  const isPdf = job.file_type === "pdf";

  return (
    <li
      data-testid={`job-row-${job.id}`}
      className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 transition-colors duration-150 ease-out hover:bg-surface-2/50"
    >
      <div className="flex min-w-0 items-center gap-3">
        {onToggle && (
          <input
            type="checkbox"
            data-testid={`row-select-${job.id}`}
            checked={selected}
            onChange={() => onToggle(job.id)}
            aria-label={`Chọn job ${job.id}`}
            className="h-4 w-4 shrink-0 accent-accent"
          />
        )}
        <span
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border bg-surface-2/60 text-muted"
          aria-hidden="true"
        >
          {isPdf ? <FileText className="h-4 w-4" /> : <ImageIcon className="h-4 w-4" />}
        </span>
        <div className="min-w-0">
          <span className="block truncate font-medium text-text">
            <span className="font-mono">#{job.id}</span> · {isPdf ? "PDF" : "Ảnh"} ·{" "}
            <span className="font-mono">{job.page_count}</span> trang
          </span>
          <div className="mt-0.5 text-xs text-muted">
            <span className="font-mono">{DATE_FORMAT.format(new Date(job.created_at))}</span>
            {duration && <span className="ml-2 font-mono">{duration}</span>}
          </div>
        </div>
      </div>
      {/* 320px: wrap + justify-end; nhãn dài → icon+aria-label dưới sm (label ẩn sm:inline). */}
      <div className="flex flex-wrap items-center justify-end gap-2">
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
            title="Tải bản gốc"
            aria-label="Tải bản gốc"
            onClick={async () => {
              // P2: same-origin blob download (presigned host unreachable via port-forward).
              // R59a: download failure surfaces as toast (no inline slot here).
              try {
                const blob = await api.downloadJobFile(job.id);
                const href = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = href;
                a.download = `job-${job.id}.${blob.type.split("/")[1] || (isPdf ? "pdf" : "jpg")}`;
                document.body.appendChild(a);
                a.click();
                a.remove();
                URL.revokeObjectURL(href);
              } catch (err) {
                toast.error(mapApiError(err));
              }
            }}
          >
            <Download className="h-4 w-4 sm:hidden" aria-hidden="true" />
            <span className="hidden sm:inline">Tải bản gốc</span>
          </Button>
        )}
        {job.status === "failed" && (
          <Button
            testid={`btn-retry-job-${job.id}`}
            size="sm"
            variant="secondary"
            title="Chạy lại"
            aria-label="Chạy lại"
            disabled={retry.isPending}
            onClick={() => retry.mutate()}
          >
            <RotateCcw className="h-4 w-4 sm:hidden" aria-hidden="true" />
            <span className="hidden sm:inline">Chạy lại</span>
          </Button>
        )}
        {cancellable && (
          <Button
            testid={`btn-cancel-job-${job.id}`}
            size="sm"
            variant="secondary"
            disabled={cancel.isPending}
            onClick={() => cancel.mutate()}
          >
            Hủy
          </Button>
        )}
        {/* Spec #1: xóa job — destructive, confirm trước khi gọi DELETE. */}
        <Button
          testid={`btn-delete-job-${job.id}`}
          size="sm"
          variant="danger"
          onClick={() => setConfirmDelete(true)}
        >
          Xóa
        </Button>
      </div>
      <ConfirmDialog
        open={confirmDelete}
        title={`Xóa job #${job.id}?`}
        message="Toàn bộ dữ liệu (file gốc, kết quả, phiên bản) sẽ bị xóa vĩnh viễn. Không thể hoàn tác."
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => {
          setConfirmDelete(false);
          deleteJob.mutate();
        }}
      />
    </li>
  );
}
