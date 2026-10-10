import type { Query } from "@tanstack/react-query";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, FileQuestion, PenLine, TriangleAlert } from "lucide-react";
import { useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ApiError, api } from "../api/client";
import type { Job } from "../api/types";
import { mapApiError } from "../lib/errors";
import { STATUS_TEXT, STATUS_TONE, PENDING_STATUSES } from "../lib/status";
import ExportBar from "../components/ExportBar";
import InfoPanel from "../components/panels/InfoPanel";
import OriginalFilePanel from "../components/panels/OriginalFilePanel";
import ResultPanel from "../components/panels/ResultPanel";
import Badge from "../components/ui/Badge";
import Button, { buttonClasses } from "../components/ui/Button";
import Card from "../components/ui/Card";
import Skeleton from "../components/ui/Skeleton";

/** Poll every 3s while pending (queued/extracting/rendering); stop once done/failed (binding, Task 4). */
const jobRefetchInterval = (q: Query<Job>): number | false =>
  q.state.data && PENDING_STATUSES.includes(q.state.data.status) ? 3000 : false;

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
  /** Toggle "Bản gốc": default full-width; ON → split 7/5 với OriginalFilePanel (luôn mount, ẩn qua `hidden`). */
  const [showOriginal, setShowOriginal] = useState(false);
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
              testid="btn-retry-job"
              onClick={async () => {
                setRetryError(null);
                try {
                  await api.retryJob(id!);
                  toast.success("Đã lên lịch chạy lại");
                  await queryClient.invalidateQueries({ queryKey: ["job", id] });
                  await queryClient.invalidateQueries({ queryKey: ["jobs"] });
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
          {/* Hủy job: pending → cancelled (204); done|failed|cancelled ẩn nút. */}
          {PENDING_STATUSES.includes(job.status) && (
            <Button
              testid="btn-cancel-job"
              variant="secondary"
              onClick={async () => {
                try {
                  await api.cancelJob(id!);
                  toast.success("Đã hủy job");
                  await queryClient.invalidateQueries({ queryKey: ["job", id] });
                  await queryClient.invalidateQueries({ queryKey: ["jobs"] });
                } catch (err) {
                  toast.error(mapApiError(err));
                }
              }}
            >
              Hủy job
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
          {/* Phase 2 Task 4: sang trang trích xuất (highlight + click-fix) — done jobs only. */}
          {job.status === "done" && result && (
            <Link
              to={`/jobs/${id}/extraction`}
              data-testid="link-extraction"
              className={buttonClasses("secondary", "md")}
            >
              Trích xuất văn bản
            </Link>
          )}
          {/* R51: toggle "Bản gốc" — split-view đối chiếu file gốc. */}
          <Button
            testid="btn-toggle-original"
            variant="secondary"
            aria-pressed={showOriginal}
            onClick={() => setShowOriginal((v) => !v)}
          >
            Bản gốc
          </Button>
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
        className={`grid gap-4 lg:gap-6 ${
          // R51 toggle: ON = ResultPanel 7 | OriginalFilePanel 5; OFF = full-width 1 cột.
          showOriginal ? "lg:grid-cols-[7fr_5fr]" : ""
        }`}
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
          {/* Luôn mount (không re-fetch); ẩn qua hidden attribute khi toggle OFF. */}
          <div data-testid="original-panel" hidden={!showOriginal}>
            <OriginalFilePanel jobId={id!} fileType={job.file_type} />
          </div>
          {/* Phase 3: bỏ job-meta card (badge "Đầu ra" + statsLine) — ExportBar 1 cụm trong rail. */}
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
