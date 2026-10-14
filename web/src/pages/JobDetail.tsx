import type { Query } from "@tanstack/react-query";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ChevronDown, FileQuestion, PenLine, TriangleAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { ApiError, api } from "../api/client";
import type { DocumentVersion, Job } from "../api/types";
import { mapApiError } from "../lib/errors";
import { STATUS_KEY, STATUS_TONE, PENDING_STATUSES } from "../lib/status";
import { translate, useT } from "../i18n";
import { useJobDoneToasts } from "../hooks/useJobDoneToasts";
import ExportBar from "../components/ExportBar";
import ConfirmDialog from "../components/ConfirmDialog";
import DownloadDropdown from "../components/DownloadDropdown";
import InfoPanel from "../components/panels/InfoPanel";
import OriginalFilePanel from "../components/panels/OriginalFilePanel";
import LayoutPreview from "../components/LayoutPreview";
import TextSection from "../components/TextSection";
import UnifiedEditor from "../components/UnifiedEditor";
import Badge from "../components/ui/Badge";
import Button from "../components/ui/Button";
import Card from "../components/ui/Card";
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
export default function JobDetail() {
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
  /** U3: section Layout collapsible — default mở, chevron rotate-180. */
  const [layoutOpen, setLayoutOpen] = useState(true);
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
  const [infoOpen, setInfoOpen] = useState(true);
  /** U1 P0: đổi :id KHÔNG remount → reset states JobDetail theo id (grid remount bằng key). */
  useEffect(() => {
    setConfirmDelete(false);
    setEditing(false);
    setEditingText(false);
    setLayoutOpen(true);
    setDownloadOpen(false);
    setRetryingLayout(false);
    setConfirmRetry(false);
    setShowHistory(false);
    setOriginalOpen(true);
    setInfoOpen(true);
    setRetryError(null);
    // oxlint-disable-next-line react/set-state-in-effect -- reset theo id (U1)
  }, [id]);

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
            {t("jd.backToList")}
          </Link>
          <h1 className="min-w-0 break-words text-xl font-bold tracking-tight sm:text-2xl">
            {t("jd.title")} <span className="font-mono">#{job.id}</span>
          </h1>
          <Badge tone={STATUS_TONE[job.status]}>{t(STATUS_KEY[job.status])}</Badge>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {/* P0-D: stale_layouts > 0 → badge + đồng bộ lại (server trả [] → mất badge). */}
          {(job.stale_layouts?.length ?? 0) > 0 && (
            <>
              <Badge testid="stale-badge" tone="warning">
                {t("jd.staleBadge")}
              </Badge>
              <Button
                testid="btn-resync-layout"
                variant="secondary"
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
                  toast.success(t("jobs.row.retryScheduled"));
                  await queryClient.invalidateQueries({ queryKey: ["job", id] });
                  await queryClient.invalidateQueries({ queryKey: ["jobs"] });
                } catch (err) {
                  // R51: inline retry-error kept; toast mirrors it (R59a).
                  setRetryError(err instanceof ApiError ? err.detail : t("jd.retryFailed"));
                  toast.error(mapApiError(err));
                }
              }}
            >
              {t("jd.retryOcr")}
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
                  toast.success(t("jobs.row.cancelled"));
                  await queryClient.invalidateQueries({ queryKey: ["job", id] });
                  await queryClient.invalidateQueries({ queryKey: ["jobs"] });
                } catch (err) {
                  toast.error(mapApiError(err));
                }
              }}
            >
              {t("jd.cancelJob")}
            </Button>
          )}
          {/* Lane I Task 6: "Vẽ lại layout" — POST retry-layout, confirm + loading + toast. */}
          {job.status === "done" && result && (
            <Button
              testid="btn-retry-layout"
              variant="secondary"
              loading={retryingLayout}
              onClick={() => setConfirmRetry(true)}
            >
              {t("jd.retryLayout")}
            </Button>
          )}
          {/* Lane I Task 5: download gộp 1 dropdown, dời lên cạnh "Chỉnh sửa". */}
          <DownloadDropdown
            jobId={id!}
            open={downloadOpen}
            onToggle={() => setDownloadOpen((v) => !v)}
          />
          {/* P0-C: lịch sử version + khôi phục (API listVersions/restoreVersion sẵn). */}
          <Button
            testid="btn-version-history"
            variant="secondary"
            aria-expanded={showHistory}
            aria-controls="version-history"
            onClick={() => setShowHistory((v) => !v)}
          >
            {t("jd.history")}
          </Button>
          {/* Spec #1: Xóa job — destructive, confirm dialog → DELETE → về list. */}
          <Button
            testid="btn-delete-job"
            variant="danger"
            onClick={() => setConfirmDelete(true)}
          >
            {t("jd.deleteJob")}
          </Button>
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

      {/*
        Wave-3 #5 → Lane I Task 2: col trái stack 2 section; col phải = collapsible
        "File gốc" + "Thông tin" (Button aria-expanded, default closed — mở mới mount).
      */}
      <div key={job.id} data-testid="detail-grid" className="grid gap-4 lg:grid-cols-12 lg:gap-6">
        <div className="flex min-w-0 flex-col gap-6 lg:col-span-7">
          {/* SECTION "Văn bản" — hiện cả khi status rendering (OCR xong). */}
          {textReady && (
            <section
              data-testid="section-text"
              aria-labelledby="section-text-title"
              className="flex flex-col gap-4"
            >
              <div className="flex items-center justify-between gap-2">
                <h2 id="section-text-title" className="text-lg font-semibold tracking-tight">
                  {t("jd.sectionText")}
                </h2>
                {/* U2: heading → edit; Text KHÔNG collapsible (chỉ scroll — U9). */}
                <Button
                  testid="btn-edit-text"
                  variant="secondary"
                  aria-pressed={editingText}
                  onClick={() => setEditingText((v) => !v)}
                >
                  {editingText ? t("editor.editing") : t("editor.edit")}
                </Button>
              </div>
              <div data-testid="panel-result" className="flex min-w-0 flex-col gap-6">
                <TextSection
                  jobId={id!}
                  regions={regions}
                  fileType={job.file_type}
                  editingText={editingText}
                  onEditingTextChange={setEditingText}
                />
              </div>
            </section>
          )}

          {/* SECTION "Layout" — preview (default) / editor khi "Chỉnh sửa". */}
          {layoutReady && result && (
            <section
              data-testid="section-layout"
              aria-labelledby="section-layout-title"
              className="flex flex-col gap-4"
            >
              <div className="flex items-center justify-between gap-2">
                <h2 id="section-layout-title" className="text-lg font-semibold tracking-tight">
                  Layout
                </h2>
                {/* U3: chevron toggle — heading → edit → chevron; aria-controls vào wrap panel. */}
                <div className="flex items-center gap-1">
                  <Button
                    testid="btn-edit-doc"
                    variant="secondary"
                    aria-pressed={editing}
                    disabled={job.status !== "done"}
                    onClick={toggleEdit}
                  >
                    <PenLine className="h-4 w-4" aria-hidden="true" />
                    {editing ? t("jd.editing") : t("jd.edit")}
                  </Button>
                  <Button
                    testid="btn-toggle-layout"
                    variant="ghost"
                    aria-expanded={layoutOpen}
                    aria-controls="layout-panel-wrap"
                    aria-label={t("jd.layoutToggleAria")}
                    onClick={() => setLayoutOpen((v) => !v)}
                  >
                    <ChevronDown
                      className={`h-4 w-4 text-muted transition duration-150 ease-out ${layoutOpen ? "rotate-180" : ""}`}
                      aria-hidden="true"
                    />
                  </Button>
                </div>
              </div>
              <div id="layout-panel-wrap">
              {layoutOpen && (
                <>
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
                <LayoutPreview job={job} fmt={layoutFmt} />
              )}
              {/* Stats line dưới preview (spec: SECTION Layout). */}
              <p data-testid="result-stats" className="text-sm text-muted">
                {t("jd.stats", { pages: job.page_count, gpu: result.gpu_seconds, model: result.model_version })}
              </p>
                </>
              )}
              </div>
              {/* WS-UI item 13: ExportBar 2 nhóm DƯỚI preview cột trái (không còn trong rail). */}
              <Card testid="panel-export">
                <ExportBar jobId={id!} />
              </Card>
            </section>
          )}
        </div>
        {/* ẢNH GỐC + Thông tin — collapsible (U6: sticky lg:top-32 = AppNav 4rem + job-header 4rem). */}
        <aside className="flex min-w-0 flex-col gap-4 lg:sticky lg:top-32 lg:col-span-5 lg:self-start">
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
              {originalOpen && <OriginalFilePanel jobId={id!} fileType={job.file_type} />}
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
              {infoOpen && <InfoPanel job={job} />}
            </div>
          </section>
        </aside>
      </div>
    </main>
  );
}
