import type { Query } from "@tanstack/react-query";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, FileQuestion, PenLine, TriangleAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ApiError, api } from "../api/client";
import type { DocumentVersion, Job } from "../api/types";
import { mapApiError } from "../lib/errors";
import { STATUS_TEXT, STATUS_TONE, PENDING_STATUSES } from "../lib/status";
import ExportBar from "../components/ExportBar";
import InfoPanel from "../components/panels/InfoPanel";
import OriginalFilePanel from "../components/panels/OriginalFilePanel";
import LayoutPreview from "../components/LayoutPreview";
import TextSection from "../components/TextSection";
import UnifiedEditor from "../components/UnifiedEditor";
import Badge from "../components/ui/Badge";
import Button, { buttonClasses } from "../components/ui/Button";
import Card from "../components/ui/Card";
import Skeleton from "../components/ui/Skeleton";

/** Poll every 3s while pending (queued/extracting/rendering); stop once done/failed (binding, Task 4). */
const jobRefetchInterval = (q: Query<Job>): number | false =>
  q.state.data && PENDING_STATUSES.includes(q.state.data.status) ? 3000 : false;

/**
 * WS-UI (spec 2026-10-13): 2 section dọc —
 * SECTION "Văn bản" (7/5: TextSection + ảnh gốc auto) — hiện cả khi rendering;
 * SECTION "Layout" (7/5: LayoutPreview / editor khi "Chỉnh sửa" + ExportBar
 * dưới preview | ảnh gốc + InfoPanel). Ảnh gốc auto-fetch, blob cache chung.
 */
export default function JobDetail() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const { data: job, isPending, isError, error } = useQuery({
    queryKey: ["job", id],
    queryFn: () => api.getJob(id!),
    refetchInterval: jobRefetchInterval,
  });
  const [retryError, setRetryError] = useState<string | null>(null);
  /** JD2: btn-edit-doc = inline edit ON THIS PAGE — section Layout: preview ↔ editor. */
  const [editing, setEditing] = useState(false);
  /** P0-C: panel "Lịch sử" — list lazy-fetch khi mở (queryKey "versions" để invalidate). */
  const [showHistory, setShowHistory] = useState(false);
  const {
    data: versions,
    isPending: versionsPending,
    isError: versionsError,
  } = useQuery({
    queryKey: ["versions", id],
    queryFn: () => api.listVersions(id!),
    enabled: showHistory,
  });
  /** P2 a11y: Escape đóng panel lịch sử. */
  useEffect(() => {
    if (!showHistory) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setShowHistory(false);
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [showHistory]);
  const editorHostRef = useRef<HTMLElement>(null);

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

  const result = job.status === "done" ? job.result : null;
  /** Section "Văn bản": OCR xong (rendering/done) → GET /extraction 200. */
  const textReady = job.result !== null && (job.status === "rendering" || job.status === "done");
  /** Section "Layout": layout artifact chỉ có khi done. P1-2: extract_only không gen layout → ẩn. */
  const layoutReady =
    result !== null && job.status === "done" && job.mode !== "extract_only";
  const regions = (job.result?.pages ?? []).flatMap((p) => p.regions);

  return (
    <main id="main" className="mx-auto max-w-[1400px] p-4 sm:p-6">
      {/* Header 3-4 dòng mobile — sticky che viewport đọc doc dài; chỉ sticky ≥lg (dưới AppNav h-16). */}
      <header
        data-testid="job-header"
        className="lg:sticky lg:top-16 z-10 -mx-4 mb-4 flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b border-border bg-surface/95 px-4 py-3 backdrop-blur sm:-mx-6 sm:px-6"
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
          {/* P0-D: stale_layouts > 0 → badge + đồng bộ lại (server trả [] → mất badge). */}
          {(job.stale_layouts?.length ?? 0) > 0 && (
            <>
              <Badge testid="stale-badge" tone="warning">
                Cần đồng bộ
              </Badge>
              <Button
                testid="btn-resync-layout"
                variant="secondary"
                onClick={async () => {
                  try {
                    await api.retryLayout(id!);
                    toast.success("Đã đồng bộ layout");
                    await queryClient.invalidateQueries({ queryKey: ["job", id] });
                  } catch (err) {
                    toast.error(mapApiError(err));
                  }
                }}
              >
                Đồng bộ lại
              </Button>
            </>
          )}
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
          {/* JD2 amendment: Edit = inline edit trong section Layout (preview ↔ editor). */}
          <Button
            testid="btn-edit-doc"
            variant="secondary"
            aria-pressed={editing}
            disabled={job.status !== "done"}
            onClick={toggleEdit}
          >
            <PenLine className="h-4 w-4" aria-hidden="true" />
            {editing ? "Đang sửa" : "Chỉnh sửa"}
          </Button>
          {/* P0-C: lịch sử version + khôi phục (API listVersions/restoreVersion sẵn). */}
          <Button
            testid="btn-version-history"
            variant="secondary"
            aria-expanded={showHistory}
            aria-controls="version-history"
            onClick={() => setShowHistory((v) => !v)}
          >
            Lịch sử
          </Button>
        </div>
      </header>
      {showHistory && (
        <section
          id="version-history"
          data-testid="version-history"
          aria-label="Lịch sử phiên bản"
          className="mb-4 rounded-card border border-border bg-surface p-4 shadow-card"
        >
          <div className="mb-3 flex items-center justify-between gap-2">
            <h2 className="text-sm font-semibold">Lịch sử phiên bản</h2>
            <Button
              testid="btn-version-history-close"
              variant="ghost"
              size="sm"
              onClick={() => setShowHistory(false)}
            >
              Đóng
            </Button>
          </div>
          <ul className="flex flex-col gap-2">
            {/* P1: không nuốt loading/error — skeleton 1 dòng, fail → role=alert. */}
            {versionsPending && (
              <li>
                <Skeleton testid="versions-skeleton" className="h-8 w-full" />
              </li>
            )}
            {versionsError && (
              <li role="alert" className="text-sm text-error">
                Không tải được lịch sử.
              </li>
            )}
            {versions?.items.map((v: DocumentVersion) => (
              <li
                key={v.id}
                /* P0-C: UNIQUE(job_id,kind,version) → version restart per kind → testid phải gồm kind. */
                data-testid={`version-row-${v.kind}-${v.version}`}
                className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-2 text-sm last:border-0 last:pb-0"
              >
                <span className="flex flex-wrap items-center gap-2">
                  <span className="font-mono font-medium">v{v.version}</span>
                  <Badge tone="neutral">{v.kind}</Badge>
                  <time dateTime={v.created_at} className="text-muted">
                    {new Date(v.created_at).toLocaleString("vi-VN")}
                  </time>
                  {/* P2: "Hiện tại" = version == MAX trong cùng kind (md snapshot kind "md" khi region edit). */}
                  {versions &&
                    v.version ===
                      Math.max(
                        ...versions.items.filter((x: DocumentVersion) => x.kind === v.kind).map((x) => x.version),
                      ) && (
                    <Badge tone="success">Hiện tại</Badge>
                  )}
                </span>
                <Button
                  testid={`btn-version-restore-${v.kind}-${v.version}`}
                  variant="secondary"
                  size="sm"
                  onClick={async () => {
                    try {
                      // vid = DocumentVersion.id (server: session.get(DocumentVersion, vid)).
                      await api.restoreVersion(id!, v.id);
                      toast.success("Đã khôi phục bản cũ");
                      await queryClient.invalidateQueries({ queryKey: ["job", id] });
                      await queryClient.invalidateQueries({ queryKey: ["versions", id] });
                    } catch (err) {
                      toast.error(mapApiError(err));
                    }
                  }}
                >
                  Khôi phục
                </Button>
              </li>
            ))}
            {versions && versions.items.length === 0 && (
              <li className="text-sm text-muted">Chưa có phiên bản nào.</li>
            )}
          </ul>
        </section>
      )}
      {retryError && (
        <p data-testid="retry-error" role="alert" className="mb-4 text-sm text-error">
          {retryError}
        </p>
      )}

      {/* SECTION 1 "Văn bản" — 7/5; hiện cả khi status rendering (OCR xong). */}
      {textReady && (
        <section
          data-testid="section-text"
          aria-labelledby="section-text-title"
          className="mb-6 flex flex-col gap-4 lg:mb-8"
        >
          <h2 id="section-text-title" className="text-lg font-semibold tracking-tight">
            Văn bản
          </h2>
          <div
            data-testid="detail-grid"
            className="grid gap-4 lg:grid-cols-[7fr_5fr] lg:gap-6"
          >
            <div
              data-testid="detail-reading"
              className="flex min-w-0 flex-col gap-4 py-2 leading-[1.6] lg:py-6"
            >
              <div data-testid="panel-result" className="flex min-w-0 flex-col gap-6">
                <TextSection jobId={id!} regions={regions} fileType={job.file_type} />
                {/* WS-UI: link đọc tiếp ở trang trích xuất đầy đủ. */}
                <Link
                  to={`/jobs/${id}/extraction`}
                  data-testid="link-extraction"
                  className={buttonClasses("secondary", "md")}
                >
                  Mở trang trích xuất đầy đủ
                </Link>
              </div>
            </div>
            <aside className="flex min-w-0 flex-col lg:sticky lg:top-16 lg:self-start">
              <OriginalFilePanel jobId={id!} fileType={job.file_type} />
            </aside>
          </div>
        </section>
      )}

      {/* SECTION 2 "Layout" — 7/5: preview (default) / editor khi "Chỉnh sửa". */}
      {layoutReady && result && (
        <section
          data-testid="section-layout"
          aria-labelledby="section-layout-title"
          className="flex flex-col gap-4"
        >
          <h2 id="section-layout-title" className="text-lg font-semibold tracking-tight">
            Layout
          </h2>
          <div className="grid gap-4 lg:grid-cols-[7fr_5fr] lg:gap-6">
            <div className="flex min-w-0 flex-col gap-4 py-2 lg:py-6">
              {editing ? (
                <UnifiedEditor
                  jobId={id!}
                  job={job}
                  markdown={result.edited_markdown ?? result.markdown}
                  editing={editing}
                  onEditingChange={setEditing}
                  hostRef={editorHostRef}
                />
              ) : (
                <LayoutPreview job={job} />
              )}
              {/* Stats line dưới preview (spec: SECTION Layout). */}
              <p data-testid="result-stats" className="text-sm text-muted">
                {job.page_count} trang · GPU {result.gpu_seconds}s · {result.model_version}
              </p>
              {/* WS-UI item 13: ExportBar 2 nhóm DƯỚI preview cột trái (không còn trong rail). */}
              <Card testid="panel-export">
                <ExportBar jobId={id!} />
              </Card>
            </div>
            <aside className="flex min-w-0 flex-col gap-4 lg:sticky lg:top-16 lg:self-start">
              {/* ẢNH GỐC: dùng lại blob cache — không fetch đôi. */}
              <OriginalFilePanel
                jobId={id!}
                fileType={job.file_type}
                testid="panel-original-layout"
              />
              <InfoPanel job={job} />
            </aside>
          </div>
        </section>
      )}

      {/* OCR chưa xong (queued/extracting/failed): status-only — original + info. */}
      {!textReady && (
        <div data-testid="detail-grid" className="grid gap-4 lg:grid-cols-[7fr_5fr] lg:gap-6">
          <div />
          <aside className="flex min-w-0 flex-col gap-4">
            <OriginalFilePanel jobId={id!} fileType={job.file_type} />
            <InfoPanel job={job} />
          </aside>
        </div>
      )}
      {/* rendering (textReady, chưa layout): InfoPanel lẻ ra dưới. */}
      {textReady && !layoutReady && (
        <aside className="mt-4 flex min-w-0 flex-col gap-4">
          <InfoPanel job={job} />
        </aside>
      )}
    </main>
  );
}
