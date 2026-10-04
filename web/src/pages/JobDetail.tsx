import type { Query } from "@tanstack/react-query";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Job } from "../api/types";
import MarkdownEditor from "../components/MarkdownEditor";
import MarkdownPreview from "../components/MarkdownPreview";
import IssuesPanel from "../components/IssuesPanel";
import ExportBar from "../components/ExportBar";

const STATUS_TEXT: Record<Job["status"], string> = {
  queued: "Đang chờ worker Colab",
  running: "Đang xử lý",
  failed: "Xử lý thất bại",
  done: "Hoàn tất",
};

/** Poll every 3s while queued/running; stop once done/failed (binding, Task 4). */
const jobRefetchInterval = (q: Query<Job>): number | false =>
  q.state.data?.status === "queued" || q.state.data?.status === "running" ? 3000 : false;

export default function JobDetail() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const { data: job } = useQuery({
    queryKey: ["job", id],
    queryFn: () => api.getJob(id!),
    refetchInterval: jobRefetchInterval,
  });

  if (!job) return null;

  return (
    <main className="mx-auto max-w-3xl p-4">
      <h1 className="mb-4 text-xl font-bold">Chi tiết công việc #{job.id}</h1>
      <p data-testid={`status-${id}`}>{STATUS_TEXT[job.status]}</p>
      {job.status === "failed" && (
        <button
          type="button"
          data-testid="btn-retry"
          onClick={async () => {
            await api.retryJob(id!);
            await queryClient.invalidateQueries({ queryKey: ["job", id] });
          }}
        >
          Thử lại
        </button>
      )}
      {job.status === "done" && job.result && (
        <>
          {/* Editor controls the source: edit first, then preview (Task 8). */}
          <MarkdownEditor
            jobId={id!}
            initial={job.result.edited_markdown ?? job.result.markdown}
          />
          <MarkdownPreview markdown={job.result.edited_markdown ?? job.result.markdown} />
          <IssuesPanel
            jobId={id!}
            regions={job.result.pages.flatMap((p) => p.regions)}
          />
          <ExportBar jobId={id!} />
        </>
      )}
    </main>
  );
}
