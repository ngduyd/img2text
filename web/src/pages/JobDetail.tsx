import type { Query } from "@tanstack/react-query";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, FileQuestion, PenLine, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ApiError, api } from "../api/client";
import type { Job } from "../api/types";
import { mapApiError } from "../lib/errors";
import { STATUS_TEXT, STATUS_TONE } from "../lib/status";
import InfoPanel from "../components/panels/InfoPanel";
import OriginalFilePanel from "../components/panels/OriginalFilePanel";
import ResultPanel from "../components/panels/ResultPanel";
import Badge from "../components/ui/Badge";
import Button from "../components/ui/Button";
import Skeleton from "../components/ui/Skeleton";

/** Poll every 3s while queued/running; stop once done/failed (binding, Task 4). */
const jobRefetchInterval = (q: Query<Job>): number | false =>
  q.state.data?.status === "queued" || q.state.data?.status === "running" ? 3000 : false;

export default function JobDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: job, isPending, isError, error } = useQuery({
    queryKey: ["job", id],
    queryFn: () => api.getJob(id!),
    refetchInterval: jobRefetchInterval,
  });
  const [retryError, setRetryError] = useState<string | null>(null);

  if (!job) {
    // Loading → Skeleton (DESIGN.md §4); never a blank page (ui-ux-dev checklist).
    return (
      <main id="main" className="mx-auto max-w-3xl p-4 sm:p-6">
        {isPending ? (
          <div data-testid="job-loading" className="flex flex-col gap-4">
            <Skeleton className="h-8 w-2/3" />
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-40 w-full" />
          </div>
        ) : (
          /* Composed empty/error state (ui-ux-dev §4): icon + title + one line + action. */
          <div className="flex items-start gap-3 rounded-card border border-border bg-surface p-4 shadow-card">
            {isError ? (
              <TriangleAlert className="mt-0.5 h-5 w-5 shrink-0 text-error" aria-hidden="true" />
            ) : (
              <FileQuestion className="mt-0.5 h-5 w-5 shrink-0 text-muted" aria-hidden="true" />
            )}
            <div className="min-w-0">
              <p className="font-medium">
                {isError ? "Không tải được công việc." : "Không tìm thấy công việc."}
              </p>
              <p className="break-words text-sm text-muted">
                {isError
                  ? mapApiError(error)
                  : "Công việc không tồn tại hoặc bạn không có quyền xem."}
              </p>
              <Link
                to="/jobs"
                className="mt-2 inline-flex items-center gap-1 text-sm text-accent-text transition duration-150 ease-out hover:underline"
              >
                <ArrowLeft className="h-4 w-4" aria-hidden="true" />
                Về danh sách công việc
              </Link>
            </div>
          </div>
        )}
      </main>
    );
  }

  return (
    <main id="main" className="mx-auto max-w-3xl p-4 sm:p-6">
      {/* Header: 1 row desktop (back · title · badges · actions), wraps on mobile (DESIGN.md §7). */}
      <header className="mb-4 flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
          <Link
            to="/jobs"
            data-testid="link-back-jobs"
            className="inline-flex items-center gap-1 text-sm text-accent-text transition duration-150 ease-out hover:underline"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            Về danh sách công việc
          </Link>
          <h1 className="min-w-0 break-words text-xl font-bold tracking-tight sm:text-2xl">
            Chi tiết công việc <span className="font-mono">#{job.id}</span>
          </h1>
          <Badge tone={STATUS_TONE[job.status]}>{STATUS_TEXT[job.status]}</Badge>
          {/* Plan D4: export format chosen at upload; legacy rows default to Markdown. */}
          <Badge tone="info" testid="job-output-format">
            Đầu ra: {job.output_format === "docx" ? "Word" : "Markdown"}
          </Badge>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {job.status === "failed" && (
            <Button
              testid="btn-retry"
              onClick={async () => {
                setRetryError(null);
                try {
                  await api.retryJob(id!);
                  toast.success("Đã chạy lại.");
                  await queryClient.invalidateQueries({ queryKey: ["job", id] });
                } catch (err) {
                  // R51: inline retry-error kept; toast mirrors it (R59a).
                  setRetryError(err instanceof ApiError ? err.detail : "Thử lại thất bại.");
                  toast.error(mapApiError(err));
                }
              }}
            >
              Thử lại
            </Button>
          )}
          {/* Plan JD: /edit route owned by another lane — navigate only. */}
          <Button
            testid="btn-edit-doc"
            variant="secondary"
            onClick={() => navigate(`/edit?job=${id}`)}
          >
            <PenLine className="h-4 w-4" aria-hidden="true" />
            Edit
          </Button>
        </div>
      </header>
      {retryError && (
        <p data-testid="retry-error" role="alert" className="mb-4 text-sm text-error">
          {retryError}
        </p>
      )}
      <div className="flex flex-col gap-4">
        <OriginalFilePanel jobId={id!} fileType={job.file_type} />
        {job.status === "done" && job.result && (
          <ResultPanel jobId={id!} result={job.result} />
        )}
        <InfoPanel job={job} />
      </div>
    </main>
  );
}
