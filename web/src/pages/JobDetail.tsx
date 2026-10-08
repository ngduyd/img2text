import type { Query } from "@tanstack/react-query";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, FileQuestion, PenLine, TriangleAlert } from "lucide-react";
import { useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ApiError, api } from "../api/client";
import type { Job, ResultPage, Verdict } from "../api/types";
import { mapApiError } from "../lib/errors";
import { STATUS_TEXT, STATUS_TONE } from "../lib/status";
import ExportBar from "../components/ExportBar";
import InfoPanel from "../components/panels/InfoPanel";
import OriginalFilePanel from "../components/panels/OriginalFilePanel";
import ResultPanel from "../components/panels/ResultPanel";
import Badge from "../components/ui/Badge";
import Button from "../components/ui/Button";
import Card from "../components/ui/Card";
import Skeleton from "../components/ui/Skeleton";

/** Poll every 3s while queued/running; stop once done/failed (binding, Task 4). */
const jobRefetchInterval = (q: Query<Job>): number | false =>
  q.state.data?.status === "queued" || q.state.data?.status === "running" ? 3000 : false;

/** Task 2 verdict stats — counts keyed by RegionOut.verdict (VERDICT_LABELS keys). */
function statsLine(pages: ResultPage[]): string {
  const regions = pages.flatMap((p) => p.regions);
  const count = (v: Verdict) => regions.filter((r) => r.verdict === v).length;
  return (
    `Tổng ${regions.length} vùng · ${count("ok")} ok · ` +
    `${count("image_unextractable")} hình ảnh · ${count("unreadable")} không trích xuất · ` +
    `${count("low_confidence")} cần kiểm tra`
  );
}

export default function JobDetail() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const { data: job, isPending, isError, error } = useQuery({
    queryKey: ["job", id],
    queryFn: () => api.getJob(id!),
    refetchInterval: jobRefetchInterval,
  });
  const [retryError, setRetryError] = useState<string | null>(null);
  /** JD2: btn-edit-doc = inline edit ON THIS PAGE (không navigate /edit). */
  const [editing, setEditing] = useState(false);
  const editorHostRef = useRef<HTMLElement>(null);

  /* Plan M: scroll + focus nguồn md-layout do UnifiedEditor tự lo khi editing=true. */

  const toggleEdit = () => {
    if (editing) {
      setEditing(false);
      document
        .querySelector('[data-testid="panel-editor"]')
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    setEditing(true);
  };

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

  // Done → 2 cột: reading column + rail. Chưa xong → 1 cột (rail thành nội dung chính).
  const result = job.status === "done" ? job.result : null;

  return (
    <main id="main" className="mx-auto max-w-[1400px] p-4 sm:p-6">
      {/* Sticky dưới AppNav (top-14, md:top-16): title + status + actions luôn thấy khi đọc doc dài. */}
      <header
        data-testid="job-header"
        className="sticky top-14 z-10 -mx-4 mb-4 flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b border-border bg-surface/95 px-4 py-3 backdrop-blur sm:-mx-6 sm:px-6 md:top-16"
      >
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
              Chạy lại OCR
            </Button>
          )}
          {/* Layout gen failed (done but layout_cache miss): re-run LLM md+docx. */}
          {job.status === "done" && result && (!job.layout_cache?.md || !job.layout_cache?.docx) && (
            <Button
              testid="btn-retry-layout"
              variant="secondary"
              onClick={async () => {
                setRetryError(null);
                try {
                  await api.retryLayout(id!);
                  toast.success("Đã tạo lại layout.");
                  await queryClient.invalidateQueries({ queryKey: ["job", id] });
                } catch (err) {
                  setRetryError(err instanceof ApiError ? err.detail : "Tạo lại layout thất bại.");
                  toast.error(mapApiError(err));
                }
              }}
            >
              Chạy lại layout
            </Button>
          )}
          {/* JD2 amendment: Edit = inline edit trên chính trang này (không còn navigate /edit). */}
          <Button
            testid="btn-edit-doc"
            variant="secondary"
            aria-pressed={editing}
            disabled={!result}
            onClick={toggleEdit}
          >
            <PenLine className="h-4 w-4" aria-hidden="true" />
            {editing ? "Đang sửa" : "Edit"}
          </Button>
        </div>
      </header>
      {retryError && (
        <p data-testid="retry-error" role="alert" className="mb-4 text-sm text-error">
          {retryError}
        </p>
      )}
      <div
        data-testid="detail-grid"
        className={`grid gap-4 lg:gap-6 ${result ? "lg:grid-cols-[minmax(0,1fr)_320px]" : ""}`}
      >
        {result && (
          <div
            data-testid="detail-reading"
            /* Plan M3: content col rộng hết cột trái (bỏ cap 75ch) — vùng Soạn thảo mở rộng. */
            className="flex min-w-0 flex-col gap-6 py-2 leading-[1.6] lg:py-6"
          >
            <ResultPanel
              jobId={id!}
              job={job}
              result={result}
              editing={editing}
              onEditingChange={setEditing}
              hostRef={editorHostRef}
            />
          </div>
        )}
        <aside data-testid="detail-rail" className="flex min-w-0 flex-col gap-4">
          <OriginalFilePanel jobId={id!} fileType={job.file_type} />
          {/* Meta compact (card rhythm px-4 py-3): output badge + stats thay vì trong reading column. */}
          <div data-testid="job-meta" className="rounded-card border border-border bg-surface px-4 py-3 shadow-card">
            {/* Plan D4: export format chosen at upload; legacy rows default to Markdown. */}
            <Badge tone="info" testid="job-output-format">
              Đầu ra: {job.output_format === "docx" ? "Word" : "Markdown"}
            </Badge>
            {result && (
              <p data-testid="result-stats" className="mt-2 text-sm leading-[1.6] text-muted">
                {statsLine(result.pages)}
              </p>
            )}
          </div>
          {result && (
            <Card testid="panel-export">
              <ExportBar jobId={id!} />
            </Card>
          )}
          <InfoPanel job={job} />
        </aside>
      </div>
    </main>
  );
}
