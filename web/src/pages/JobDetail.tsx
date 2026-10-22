import type { Query } from "@tanstack/react-query";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ChevronDown,
  FileQuestion,
  Image as ImageIcon,
  Maximize2,
  Minimize2,
  TriangleAlert,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ApiError, api } from "../api/client";
import type { DocumentVersion, Job } from "../api/types";
import { mapApiError } from "../lib/errors";
import { STATUS_KEY, STATUS_TONE, PENDING_STATUSES } from "../lib/status";
import { translate, useT } from "../i18n";
import { useJobDoneToasts } from "../hooks/useJobDoneToasts";
import ConfirmDialog from "../components/ConfirmDialog";
import DownloadDropdown from "../components/DownloadDropdown";
import InfoPanel from "../components/panels/InfoPanel";
import OriginalFilePanel from "../components/panels/OriginalFilePanel";
import LayoutPreview from "../components/LayoutPreview";
import PageShell from "../components/PageShell";
import TextSection from "../components/TextSection";
import UnifiedEditor from "../components/UnifiedEditor";
import Badge from "../components/ui/Badge";
import Button from "../components/ui/Button";
import Skeleton from "../components/ui/Skeleton";

/** Poll every 3s while pending (queued/extracting/rendering); stop once done/failed (binding, Task 4). */
const jobRefetchInterval = (q: Query<Job>): number | false =>
  q.state.data && PENDING_STATUSES.includes(q.state.data.status) ? 3000 : false;

/**
 * WS-UI (spec 2026-10-13, wave-3 #5-6): wrapper grid DUY NHẤT —
 * col trái stack SECTION "Văn bản" (TextSection, hiện cả khi rendering) +
 * SECTION "Layout" (LayoutPreview / editor khi "Chỉnh sửa" + ExportBar);
 * col phải = collapsible "File gốc" + "Thông tin" (Lane I Task 2, bỏ sticky).
 */
export type JobSection = "overview" | "text" | "layout";

const SUBPAGES = [
  { key: "overview", path: "", testid: "subnav-overview", labelKey: "jd.overview" },
  { key: "text", path: "/text", testid: "subnav-text", labelKey: "jd.sectionText" },
  { key: "layout", path: "/layout", testid: "subnav-layout", labelKey: "jd.layout" },
] as const;

/** SPEC-ui-redesign D3: mỗi route render ĐÚNG 1 section (overview | text | layout). */
export default function JobDetail({ section = "overview" }: { section?: JobSection } = {}) {
  const { t } = useT();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: job, isPending, isError, error } = useQuery({
    queryKey: ["job", id],
    queryFn: () => api.getJob(id!),
    refetchInterval: jobRefetchInterval,
  });
  // Spec #2: pending → done/failed trong poll → toast + Notification (best-effort).
  useJobDoneToasts(
    job ? [{ id: job.id, status: job.status, error: job.error }] : undefined,
  );
  /** Spec #1: confirm xóa job (destructive) — mở từ header. */
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);
  /** JD2: btn-edit-doc = inline edit ON THIS PAGE — section Layout: preview ↔ editor. */
  const [editing, setEditing] = useState(false);
  /** U2: nút Edit text dời ra heading row section Text (controlled xuống TextSection). */
  const [editingText, setEditingText] = useState(false);
  /** Lane I Task 6: dropdown "Tải xuống" ở header (gộp 4 định dạng text). */
  const [downloadOpen, setDownloadOpen] = useState(false);
  /** U7: bỏ switch MD/Word — fmt fixed init theo job.output_format. */
  const layoutFmt = job?.output_format === "docx" ? "docx-layout" : "md-layout";
  const [retryingLayout, setRetryingLayout] = useState(false);
  const [confirmRetry, setConfirmRetry] = useState(false);
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
  /** U4+U5: File gốc + Thông tin = collapsible, mặc định MỞ (justify-between label/chevron). */
  const [originalOpen, setOriginalOpen] = useState(true);
  /** D8: ảnh gốc đối chiếu ngay trong trang layout (không phải sang Tổng quan). */
  const [showOriginal, setShowOriginal] = useState(false);
  /** Focus mode: editor chiếm trọn viewport, Escape để thoát. */
  const [zen, setZen] = useState(false);
  const [infoOpen, setInfoOpen] = useState(true);
  /** U1 P0: đổi :id KHÔNG remount → reset states JobDetail theo id (grid remount bằng key). */
  useEffect(() => {
    setConfirmDelete(false);
    setEditing(false);
    setEditingText(false);
    setDownloadOpen(false);
    setRetryingLayout(false);
    setConfirmRetry(false);
    setShowHistory(false);
    setOriginalOpen(true);
    setInfoOpen(true);
    setShowOriginal(false);
    setZen(false);
    setRetryError(null);
    // oxlint-disable-next-line react/set-state-in-effect -- reset theo id (U1)
  }, [id]);

  useEffect(() => {
    if (!zen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setZen(false);
    };
    document.addEventListener("keydown", onKey);
    // Khóa scroll nền khi editor chiếm toàn viewport.
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [zen]);

  /** Lane I Task 6: confirm "Vẽ lại layout" → POST retry-layout + loading + toast (R59). */
  const confirmRetryLayout = async () => {
    setConfirmRetry(false);
    setRetryingLayout(true);
    setRetryError(null);
    try {
      await api.retryLayout(id!);
      toast.success(t("jd.retryLayoutDone"));
      await queryClient.invalidateQueries({ queryKey: ["job", id] });
    } catch (err) {
      setRetryError(err instanceof ApiError ? err.detail : t("jd.retryLayoutFailed"));
      toast.error(mapApiError(err));
    } finally {
      setRetryingLayout(false);
    }
  };

  if (!job) {
    // Loading → Skeleton (DESIGN.md §4); never a blank page (ui-ux-dev checklist).
    return (
      <PageShell width="data">
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
                {isError ? t("jd.loadFailedTitle") : t("jd.notFoundTitle")}
              </p>
              <p className="break-words text-sm text-muted">
                {isError ? mapApiError(error) : t("jd.notFoundBody")}
              </p>
              <Link
                to="/jobs"
                className="mt-2 inline-flex items-center gap-1 text-sm text-accent-text transition duration-150 ease-out hover:underline"
              >
                <ArrowLeft className="h-4 w-4" aria-hidden="true" />
                {t("jd.backToList")}
              </Link>
            </div>
          </div>
        )}
      </PageShell>
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
    <PageShell width={section === "overview" ? "data" : "editor"}>
      {/* D1/D4: MỘT thanh sticky duy nhất — back · tên job · subnav · hành động.
          Trước đây 5 hàng chrome (header 3 dòng + subnav + h1 + card + toolbar)
          đẩy nội dung xuống ~440px; giờ nội dung bắt đầu ở ~150px. */}
      <header
        data-testid="job-header"
        /* overview dùng shell `data` (main có px-4) → -mx để tràn viền; text/layout
           dùng shell `editor` (main px-0) → -mx sẽ tràn ngang 16px ở 320px. */
        className={[
          "lg:sticky lg:top-16 z-10 mb-4 flex flex-wrap items-center gap-x-2 gap-y-2 border-b border-border bg-surface/95 px-4 py-2 backdrop-blur sm:px-6",
          section === "overview" ? "-mx-4 sm:-mx-6" : "",
        ].join(" ")}
      >
        <Link
          to="/jobs"
          data-testid="link-back-jobs"
          aria-label={t("jd.backToList")}
          title={t("jd.backToList")}
          className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-muted transition duration-150 ease-out hover:bg-surface-2 hover:text-text"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        </Link>
        <h1 className="flex min-w-0 items-center gap-2 text-base font-semibold tracking-tight">
          <span className="font-mono text-muted">#{job.id}</span>
          <span className="max-w-[10ch] truncate sm:max-w-[22ch]">{job.filename || t("jd.title")}</span>
        </h1>
        <Badge tone={STATUS_TONE[job.status]}>{t(STATUS_KEY[job.status])}</Badge>
        <nav
          data-testid="job-subnav"
          aria-label={t("jd.subnavAria")}
          className="-mx-1 flex min-w-0 max-w-full items-center gap-0.5 overflow-x-auto px-1 sm:mx-0 sm:ml-2 sm:overflow-visible sm:px-0"
        >
          {SUBPAGES.map(({ key, path, testid, labelKey }) => (
            <Link
              key={key}
              to={`/jobs/${id}${path}`}
              data-testid={testid}
              aria-current={section === key ? "page" : undefined}
              className={[
                "rounded-md px-2.5 py-1.5 text-sm transition duration-150 ease-out",
                section === key
                  ? "bg-surface-2 font-semibold text-text"
                  : "text-muted hover:bg-surface-2 hover:text-text",
              ].join(" ")}
            >
              {t(labelKey)}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
          {/* D4: tối đa 1 primary + 1 secondary hiện; còn lại nằm trong ⋯. */}
          {section === "layout" && layoutReady && (
            <>
              <Button
                testid="btn-toggle-original-layout"
                variant="ghost"
                size="sm"
                aria-pressed={showOriginal}
                onClick={() => setShowOriginal((v) => !v)}
              >
                <ImageIcon className="h-4 w-4" aria-hidden="true" />
                {t("jd.showOriginal")}
              </Button>
              <Button
                testid="btn-zen"
                variant="ghost"
                size="sm"
                aria-pressed={zen}
                aria-label={zen ? t("jd.exitZen") : t("jd.zen")}
                title={zen ? t("jd.exitZen") : t("jd.zen")}
                onClick={() => setZen((v) => !v)}
              >
                {zen ? <Minimize2 className="h-4 w-4" aria-hidden="true" /> : <Maximize2 className="h-4 w-4" aria-hidden="true" />}
              </Button>
              <Button
                testid="btn-edit-doc"
                variant={editing ? "primary" : "secondary"}
                size="sm"
                aria-pressed={editing}
                disabled={job.status !== "done"}
                onClick={() => setEditing((v) => !v)}
              >
                {editing ? t("jd.editing") : t("jd.edit")}
              </Button>
            </>
          )}
          <Button
            testid="btn-version-history"
            variant="ghost"
            size="sm"
            aria-expanded={showHistory}
            aria-controls="version-history"
            onClick={() => setShowHistory((v) => !v)}
          >
            {t("jd.history")}
          </Button>
          <DownloadDropdown
            jobId={id!}
            layoutReady={layoutReady}
            open={downloadOpen}
            onToggle={() => setDownloadOpen((v) => !v)}
          />
          <details className="relative">
            <summary
              data-testid="btn-job-more"
              aria-label={t("jobs.row.more")}
              title={t("jobs.row.more")}
              className="inline-flex h-9 w-9 cursor-pointer list-none items-center justify-center rounded-md text-muted transition duration-150 ease-out hover:bg-surface-2 hover:text-text [&::-webkit-details-marker]:hidden"
            >
              <span aria-hidden="true">⋯</span>
            </summary>
            <div
              data-testid="job-more-panel"
              className="absolute right-0 z-20 mt-1 flex w-56 flex-col rounded-md border border-border bg-surface p-1 shadow-lg"
            >
              {(job.stale_layouts?.length ?? 0) > 0 && (
                <>
                  <span className="px-3 py-1.5">
                    <Badge testid="stale-badge" tone="warning">
                      {t("jd.staleBadge")}
                    </Badge>
                  </span>
                  <MenuBtn
                    testid="btn-resync-layout"
                  onClick={async () => {
                    try {
                      await api.retryLayout(id!);
                      toast.success(t("jd.resyncDone"));
                      await queryClient.invalidateQueries({ queryKey: ["job", id] });
                    } catch (err) {
                      toast.error(mapApiError(err));
                    }
                  }}
                  >
                    {t("jd.resync")}
                  </MenuBtn>
                </>
              )}
              {job.status === "failed" && (
                <MenuBtn
                  testid="btn-retry-job"
                  onClick={async () => {
                    setRetryError(null);
                    try {
                      await api.retryJob(id!);
                      toast.success(t("jobs.row.retryScheduled"));
                      await queryClient.invalidateQueries({ queryKey: ["job", id] });
                      await queryClient.invalidateQueries({ queryKey: ["jobs"] });
                    } catch (err) {
                      setRetryError(err instanceof ApiError ? err.detail : t("jd.retryFailed"));
                      toast.error(mapApiError(err));
                    }
                  }}
                >
                  {t("jd.retryOcr")}
                </MenuBtn>
              )}
              {PENDING_STATUSES.includes(job.status) && (
                <MenuBtn
                  testid="btn-cancel-job"
                  onClick={async () => {
                    try {
                      await api.cancelJob(id!);
                      toast.success(t("jobs.row.cancelled"));
                      await queryClient.invalidateQueries({ queryKey: ["job", id] });
                      await queryClient.invalidateQueries({ queryKey: ["jobs"] });
                    } catch (err) {
                      toast.error(mapApiError(err));
                    }
                  }}
                >
                  {t("jd.cancelJob")}
                </MenuBtn>
              )}
              {job.status === "done" && result && (
                <MenuBtn
                  testid="btn-retry-layout"
                  disabled={retryingLayout}
                  onClick={() => setConfirmRetry(true)}
                >
                  {t("jd.retryLayout")}
                </MenuBtn>
              )}
              <MenuBtn testid="btn-delete-job" tone="danger" onClick={() => setConfirmDelete(true)}>
                {t("jd.deleteJob")}
              </MenuBtn>
            </div>
          </details>
        </div>
      </header>
      <ConfirmDialog
        open={confirmDelete}
        title={t("jobs.row.deleteTitle", { id: job.id })}
        message={t("jobs.row.deleteMessage")}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => {
          setConfirmDelete(false);
          void (async () => {
            try {
              await api.deleteJob(id!);
              toast.success(t("jobs.row.deleted"));
              await queryClient.invalidateQueries({ queryKey: ["jobs"] });
              navigate("/jobs");
            } catch (err) {
              toast.error(mapApiError(err));
            }
          })();
        }}
      />
      {/* Lane I Task 6: confirm "Vẽ lại layout" (LLM re-run md+docx). */}
      <ConfirmDialog
        open={confirmRetry}
        title={t("jd.retryLayoutConfirmTitle")}
        message={t("jd.retryLayoutConfirmMessage")}
        confirmLabel={t("jd.retryLayoutShort")}
        onCancel={() => setConfirmRetry(false)}
        onConfirm={() => void confirmRetryLayout()}
      />
      {showHistory && (
        <section
          id="version-history"
          data-testid="version-history"
          aria-label={t("jd.historyAria")}
          className="mb-4 rounded-card border border-border bg-surface p-4 shadow-card"
        >
          <div className="mb-3 flex items-center justify-between gap-2">
            <h2 className="text-sm font-semibold">{t("jd.historyTitle")}</h2>
            <Button
              testid="btn-version-history-close"
              variant="ghost"
              size="sm"
              onClick={() => setShowHistory(false)}
            >
              {t("common.close")}
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
                {t("jd.historyError")}
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
                    {new Date(v.created_at).toLocaleString(translate("i18n.locale"))}
                  </time>
                  {/* P2: "Hiện tại" = version == MAX trong cùng kind (md snapshot kind "md" khi region edit). */}
                  {versions &&
                    v.version ===
                      Math.max(
                        ...versions.items.filter((x: DocumentVersion) => x.kind === v.kind).map((x) => x.version),
                      ) && (
                    <Badge tone="success">{t("jd.current")}</Badge>
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
                      toast.success(t("jd.restored"));
                      await queryClient.invalidateQueries({ queryKey: ["job", id] });
                      await queryClient.invalidateQueries({ queryKey: ["versions", id] });
                    } catch (err) {
                      toast.error(mapApiError(err));
                    }
                  }}
                >
                  {t("jd.restore")}
                </Button>
              </li>
            ))}
            {versions && versions.items.length === 0 && (
              <li className="text-sm text-muted">{t("jd.noVersions")}</li>
            )}
          </ul>
        </section>
      )}
      {retryError && (
        <p data-testid="retry-error" role="alert" className="mb-4 text-sm text-error">
          {retryError}
        </p>
      )}

      {section === "overview" && (
        <div key={job.id} data-testid="detail-grid" className="grid gap-4 lg:grid-cols-12 lg:gap-6">
          <div className="flex min-w-0 flex-col gap-6 lg:col-span-7">
            {textReady && (
              <LinkCard
                to={`/jobs/${id}/text`}
                testid="link-open-text"
                title={t("jd.sectionText")}
                desc={t("jd.textDesc")}
              />
            )}
            {layoutReady && (
              <LinkCard
                to={`/jobs/${id}/layout`}
                testid="link-open-layout"
                title={t("jd.layout")}
                desc={t("jd.layoutDesc")}
              />
            )}
            {!textReady && !layoutReady && (
              <p data-testid="not-ready" className="text-sm text-muted">
                {t("jd.notReadyYet")}
              </p>
            )}
            {result && layoutReady && (
              // Card "Xuất layout" bỏ: 2 định dạng layout đã gộp vào dropdown
              // "Tải xuống" ở header (trước đây 1 card chỉ để chứa 1 nút).
              <p data-testid="result-stats" className="text-sm text-muted">
                {t("jd.stats", {
                  pages: job.page_count,
                  gpu: result.gpu_seconds,
                  model: result.model_version,
                })}
              </p>
            )}
          </div>
          {/* ẢNH GỐC + Thông tin — collapsible, mặc định mở. */}
          <aside className="flex min-w-0 flex-col gap-4 lg:col-span-5 lg:self-start">
            <section className="rounded-card border border-border bg-surface shadow-card">
              <h2>
                <Button
                  testid="btn-toggle-original"
                  variant="ghost"
                  aria-expanded={originalOpen}
                  aria-controls="original-panel-wrap"
                  className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left text-base font-semibold"
                  onClick={() => setOriginalOpen((v) => !v)}
                >
                  {t("jd.originalFile")}
                  <ChevronDown
                    className={`h-4 w-4 text-muted transition duration-150 ease-out ${originalOpen ? "rotate-180" : ""}`}
                    aria-hidden="true"
                  />
                </Button>
              </h2>
              <div id="original-panel-wrap" className={originalOpen ? "border-t border-border p-4" : "hidden"}>
                {originalOpen && <OriginalFilePanel jobId={id!} fileType={job.file_type} bare />}
              </div>
            </section>
            <section className="rounded-card border border-border bg-surface shadow-card">
              <h2>
                <Button
                  testid="btn-toggle-info"
                  variant="ghost"
                  aria-expanded={infoOpen}
                  aria-controls="info-panel-wrap"
                  className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left text-base font-semibold"
                  onClick={() => setInfoOpen((v) => !v)}
                >
                  {t("jd.infoTitle")}
                  <ChevronDown
                    className={`h-4 w-4 text-muted transition duration-150 ease-out ${infoOpen ? "rotate-180" : ""}`}
                    aria-hidden="true"
                  />
                </Button>
              </h2>
              <div id="info-panel-wrap" className={infoOpen ? "border-t border-border p-4" : "hidden"}>
                {infoOpen && <InfoPanel job={job} bare />}
              </div>
            </section>
          </aside>
        </div>
      )}

      {section === "text" && (
        <div key={job.id} data-testid="detail-text" className="flex flex-col gap-4 px-4 sm:px-6">
          {textReady ? (
            <TextSection
              jobId={id!}
              regions={regions}
              fileType={job.file_type}
              editingText={editingText}
              onEditingTextChange={setEditingText}
            />
          ) : (
            <p className="text-sm text-muted">{t("jd.textNotReady")}</p>
          )}
        </div>
      )}

      {section === "layout" && (
        <div
          key={job.id}
          data-testid="detail-layout"
          className={
            zen
              ? "fixed inset-0 z-40 flex flex-col gap-4 overflow-auto bg-surface p-4"
              : "flex flex-col gap-4 px-4 sm:px-6"
          }
        >
          {layoutReady && result ? (
            <>
              {/* D8: ảnh gốc để đối chiếu khi sửa. Xếp DỌC chứ không chia cột:
                  3 pane (ảnh gốc | editor | A4) ở 1200px sẽ bóp cả hai bên. */}
              <div className={showOriginal ? "flex min-w-0 flex-col gap-4" : "min-w-0"}>
                {showOriginal && (
                  <div className="max-h-[45vh] min-w-0 overflow-auto">
                    <OriginalFilePanel
                      jobId={id!}
                      fileType={job.file_type}
                      testid="panel-original-layout"
                    />
                  </div>
                )}
                <div className="min-w-0">
                  {editing ? (
                    <UnifiedEditor
                      jobId={id!}
                      job={job}
                      markdown={result.edited_markdown ?? result.markdown}
                      editing={editing}
                      hostRef={editorHostRef}
                    />
                  ) : (
                    <LayoutPreview job={job} fmt={layoutFmt} />
                  )}
                </div>
              </div>
            </>
          ) : (
            <p className="text-sm text-muted">{t("jd.layoutNotReady")}</p>
          )}
        </div>
      )}
    </PageShell>
  );
}

/** Item trong menu ⋯ của header — button thường, không role="menu" (pattern disclosure). */
function MenuBtn({
  testid,
  onClick,
  tone = "default",
  disabled = false,
  "aria-expanded": ariaExpanded,
  children,
}: {
  testid: string;
  onClick: (e: React.MouseEvent<HTMLButtonElement>) => void;
  tone?: "default" | "danger";
  disabled?: boolean;
  "aria-expanded"?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      data-testid={testid}
      disabled={disabled}
      aria-expanded={ariaExpanded}
      onClick={onClick}
      className={[
        "cursor-pointer rounded-sm px-3 py-2 text-left text-sm transition duration-150 ease-out hover:bg-surface-2 disabled:cursor-not-allowed disabled:opacity-50",
        tone === "danger" ? "text-error" : "text-text",
      ].join(" ")}
    >
      {children}
    </button>
  );
}

/** Nhãn + mô tả cho 2 trang con (Overview). */
function LinkCard({
  to,
  testid,
  title,
  desc,
}: {
  to: string;
  testid: string;
  title: string;
  desc: string;
}) {
  return (
    <Link
      to={to}
      data-testid={testid}
      className="group flex items-start justify-between gap-4 rounded-card border border-border bg-surface p-4 transition duration-150 ease-out hover:border-accent-text/40 hover:bg-surface-2"
    >
      <span className="min-w-0">
        <span className="block text-base font-semibold">{title}</span>
        <span className="mt-1 block text-sm text-muted">{desc}</span>
      </span>
      <span aria-hidden="true" className="shrink-0 text-accent-text">
        →
      </span>
    </Link>
  );
}
