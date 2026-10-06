import type { Query } from "@tanstack/react-query";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
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

/** Poll every 3s while queued/running; stop once done/failed (binding, Task 4). */
const jobRefetchInterval = (q: Query<Job>): number | false =>
  q.state.data?.status === "queued" || q.state.data?.status === "running" ? 3000 : false;

export default function JobDetail() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const { data: job, isPending } = useQuery({
    queryKey: ["job", id],
    queryFn: () => api.getJob(id!),
    refetchInterval: jobRefetchInterval,
  });
  const [retryError, setRetryError] = useState<string | null>(null);

  if (!job) {
    // Loading state instead of blank page (ui-ux-dev empty/loading checklist).
    return (
      <main id="main" className="mx-auto max-w-3xl p-4 sm:p-6">
        {isPending ? (
          <p data-testid="job-loading" className="text-sm text-muted">
            Đang tải công việc…
          </p>
        ) : null}
      </main>
    );
  }

  return (
    <main id="main" className="mx-auto max-w-3xl p-4 sm:p-6">
      <Link
        to="/"
        data-testid="link-back-jobs"
        className="mb-3 inline-flex items-center gap-1 text-sm text-accent-text transition duration-150 ease-out hover:underline"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        Về danh sách công việc
      </Link>
      {/* Header row: title + status badge + actions — wraps on mobile (DESIGN.md §7). */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-bold tracking-tight">
            Chi tiết công việc <span className="font-mono">#{job.id}</span>
          </h1>
          <Badge tone={STATUS_TONE[job.status]}>{STATUS_TEXT[job.status]}</Badge>
        </div>
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
      </div>
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
