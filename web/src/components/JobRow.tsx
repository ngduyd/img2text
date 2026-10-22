import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { FileText, Image as ImageIcon, MoreHorizontal } from "lucide-react";
import { toast } from "sonner";
import { api } from "../api/client";
import type { JobListItem } from "../api/types";
import { mapApiError } from "../lib/errors";
// Single spelling + tone per status (spec: shell, panels, badges share lib/status).
import { STATUS_KEY, STATUS_TONE, PENDING_STATUSES } from "../lib/status";
import { translate, useT } from "../i18n";
import Badge from "./ui/Badge";
import Button from "./ui/Button";
import ConfirmDialog from "./ConfirmDialog";

function formatDuration(ms: number): string {
  const s = Math.round(ms / 1000);
  return s < 60
    ? translate("jobs.row.durationSec", { s })
    : translate("jobs.row.durationMin", { m: Math.round(s / 60) });
}

/** 1 mục trong menu ⋯: full-width, tự ẩn khi `show` false. */
function MenuAction({
  testid,
  show,
  label,
  onClick,
  disabled = false,
  danger = false,
}: {
  testid: string;
  show: boolean;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
}) {
  if (!show) return null;
  return (
    <Button
      testid={testid}
      size="sm"
      variant={danger ? "danger" : "ghost"}
      disabled={disabled}
      onClick={onClick}
      className="w-full justify-start"
    >
      {label}
    </Button>
  );
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
  const { t } = useT();
  const queryClient = useQueryClient();
  const dateFormat = new Intl.DateTimeFormat(translate("i18n.locale"), { dateStyle: "medium", timeStyle: "short" });
  const retry = useMutation({
    mutationFn: () => api.retryJob(job.id),
    onSuccess: () => {
      // Plan job-phases R59: retry upsert lịch chạy lại.
      toast.success(translate("jobs.row.retryScheduled"));
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (err) => toast.error(mapApiError(err)),
  });
  const cancel = useMutation({
    mutationFn: () => api.cancelJob(job.id),
    onSuccess: () => {
      toast.success(translate("jobs.row.cancelled"));
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (err) => toast.error(mapApiError(err)),
  });
  const deleteJob = useMutation({
    mutationFn: () => api.deleteJob(job.id),
    onSuccess: () => {
      toast.success(translate("jobs.row.deleted"));
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
            aria-label={t("jobs.row.selectAria", { id: job.id })}
            className="h-6 w-6 shrink-0 accent-accent"
          />
        )}
        <span
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border bg-surface-2/60 text-muted"
          aria-hidden="true"
        >
          {isPdf ? <FileText className="h-4 w-4" /> : <ImageIcon className="h-4 w-4" />}
        </span>
        <div className="min-w-0">
          <Link
            to={`/jobs/${job.id}`}
            data-testid={`btn-view-${job.id}`}
            className="block truncate font-medium text-text hover:text-accent-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          >
            <span className="font-mono">#{job.id}</span> · {isPdf ? "PDF" : t("jobs.row.image")} ·{" "}
            <span className="font-mono">{job.page_count}</span>{" "}
            {job.page_count === 1 ? t("jobs.row.pageOne") : t("jobs.row.pages")}
          </Link>
          <div className="mt-0.5 text-xs text-muted">
            <span className="font-mono">{dateFormat.format(new Date(job.created_at))}</span>
            {duration && <span className="ml-2 font-mono">{duration}</span>}
          </div>
        </div>
      </div>
      {/* D4: badge + 1 nút ⋯ — thao tác phụ nằm trong menu (không quá 3 control/hàng). */}
      <div className="flex flex-wrap items-center justify-end gap-2">
        <Badge tone={STATUS_TONE[job.status]} testid={`badge-${job.id}`}>
          {t(STATUS_KEY[job.status])}
        </Badge>
        <details data-testid={`row-menu-${job.id}`} className="relative">
          <summary
            data-testid={`btn-menu-${job.id}`}
            aria-label={t("jobs.row.more")}
            title={t("jobs.row.more")}
            className="flex cursor-pointer list-none items-center justify-center rounded-md border border-border bg-surface px-3 py-1 text-sm text-text transition duration-150 ease-out hover:bg-surface-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent [&::-webkit-details-marker]:hidden"
          >
            <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
          </summary>
          {/* Click 1 mục → đóng menu (details native, không cần state React). */}
          {/* Disclosure (details/summary), KHÔNG phải ARIA menu: <summary> đã có
              aria-expanded, item là button thường → đừng gắn role="menu" sai pattern. */}
          <div
            data-testid={`row-menu-panel-${job.id}`}
            className="absolute right-0 z-20 mt-1 flex w-48 flex-col gap-1 rounded-card border border-border bg-surface p-1 shadow-card"
            onClick={(e) => {
              const d = e.currentTarget.closest("details");
              if (d) d.open = false;
            }}
          >
            <MenuAction
              testid={`btn-dl-original-${job.id}`}
              show={job.status === "done"}
              label={t("jobs.row.downloadOriginal")}
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
            />
            <MenuAction
              testid={`btn-retry-job-${job.id}`}
              show={job.status === "failed"}
              label={t("jobs.row.retry")}
              disabled={retry.isPending}
              onClick={() => retry.mutate()}
            />
            <MenuAction
              testid={`btn-cancel-job-${job.id}`}
              show={cancellable}
              label={t("jobs.row.cancel")}
              disabled={cancel.isPending}
              onClick={() => cancel.mutate()}
            />
            {/* Spec #1: xóa job — destructive, confirm trước khi gọi DELETE. */}
            <MenuAction
              testid={`btn-delete-job-${job.id}`}
              show
              danger
              label={t("jobs.row.delete")}
              onClick={() => setConfirmDelete(true)}
            />
          </div>
        </details>
      </div>
      <ConfirmDialog
        open={confirmDelete}
        title={t("jobs.row.deleteTitle", { id: job.id })}
        message={t("jobs.row.deleteMessage")}
        confirmLabel={t("jobs.row.delete")}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => {
          setConfirmDelete(false);
          deleteJob.mutate();
        }}
      />
    </li>
  );
}
