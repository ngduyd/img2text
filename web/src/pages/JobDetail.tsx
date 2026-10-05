import type { Query } from "@tanstack/react-query";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ApiError, api } from "../api/client";
import type { Job } from "../api/types";
import { mapApiError } from "../lib/errors";
import InfoPanel from "../components/panels/InfoPanel";
import OriginalFilePanel from "../components/panels/OriginalFilePanel";
import ResultPanel from "../components/panels/ResultPanel";
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
      <main id="main" className="mx-auto max-w-3xl p-4">
        {isPending ? (
          <p data-testid="job-loading" className="text-sm text-muted">
            Đang tải công việc…
          </p>
        ) : null}
      </main>
    );
  }

  return (
    <main id="main" className="mx-auto max-w-3xl p-4">
      <Link
        to="/"
        data-testid="link-back-jobs"
        className="mb-2 inline-block text-sm text-accent-text hover:underline"
      >
        ← Về danh sách công việc
      </Link>
      <h1 className="mb-4 text-xl font-bold">Chi tiết công việc #{job.id}</h1>
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
      {retryError && (
        <p data-testid="retry-error" role="alert" className="text-sm text-error">
          {retryError}
        </p>
      )}
      <div className="mt-4 flex flex-col gap-4">
        <OriginalFilePanel jobId={id!} fileType={job.file_type} />
        {job.status === "done" && job.result && (
          <ResultPanel jobId={id!} result={job.result} />
        )}
        <InfoPanel job={job} />
      </div>
    </main>
  );
}
