import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Inbox } from "lucide-react";
import { toast } from "sonner";
import { ApiError, api } from "../api/client";
import type { JobMode } from "../api/types";
import CropDialog from "../components/CropDialog";
import JobRow from "../components/JobRow";
import MultiFileUpload from "../components/MultiFileUpload";
import PageSelectDialog, { type PageSelectEntry } from "../components/PageSelectDialog";
import StatusFilterTabs from "../components/StatusFilterTabs";
import SubmitModal, { type SubmitFormat } from "../components/SubmitModal";
import { mapApiError } from "../lib/errors";
import { useJobDoneToasts } from "../hooks/useJobDoneToasts";
import type { StatusFilter } from "../components/StatusFilterTabs";
import PageShell from "../components/PageShell";
import PageHeader from "../components/PageHeader";
import EmptyState from "../components/ui/EmptyState";
import Pagination, { pageWindow } from "../components/ui/Pagination";
import Select from "../components/ui/Select";
import { Stat } from "../components/ui/Stat";
import Button from "../components/ui/Button";
import Skeleton from "../components/ui/Skeleton";
import { PENDING_STATUSES } from "../lib/status";
import { useT } from "../i18n";

export { pageWindow };

export default function Jobs() {
  const navigate = useNavigate();
  const { t } = useT();
  const queryClient = useQueryClient();
  // Phase 4: server-side page state — mỗi trang 10 job (mặc định server).
  const [page, setPage] = useState(1);
  // Spec #3: search debounced 300ms + sort server-side.
  const [search, setSearch] = useState("");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<"newest" | "oldest">("newest");
  useEffect(() => {
    const t = setTimeout(() => setQ(search.trim()), 300);
    return () => clearTimeout(t);
  }, [search]);
  // Phase 4: selection cho bulk retry — đổi trang → reset (chọn chỉ sống trong trang hiện tại).
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const changePage = (next: number) => {
    setSelected(new Set());
    setPage(next);
  };
  // Spec #3: đổi search/sort/filter → về trang 1 (params khác → list khác).
  const resetToFirstPage = () => {
    setSelected(new Set());
    setPage(1);
  };
  const [filter, setFilter] = useState<StatusFilter>("all");
  const { data: jobs, isLoading } = useQuery({
    queryKey: ["jobs", page, q, sort, filter],
    queryFn: () => api.listJobs(page, 10, { q, sort, status: filter === "all" ? undefined : filter }),
    // Spec #2: poll 3s khi còn pending — chuyển done/failed mới thấy được để toast.
    refetchInterval: (q) =>
      q.state.data?.items.some((j) => PENDING_STATUSES.includes(j.status)) ? 3000 : false,
  });
  // Upload flow (spec U1-U3): Gửi → SubmitModal (mode+format) → merge → presign (R2) → tạo job.
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me });
  // ponytail: gate only after me resolves — server enforces anyway.
  const denied = me !== undefined && !(me?.ocr_enabled ?? false);
  // "uploading" = POST form → storage (XHR progress), "counting" = pdf.js đếm trang.
  const [phase, setPhase] = useState<"idle" | "uploading" | "counting">("idle");
  const [percent, setPercent] = useState(0);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  // Gửi gate: beforeSubmit của MultiFileUpload resolve qua modal confirm/cancel.
  const submitGate = useRef<((ok: boolean) => void) | null>(null);
  const choiceRef = useRef<{ mode: JobMode; output_format: SubmitFormat } | null>(null);
  const [crop, setCrop] = useState<{ blob: Blob; name: string } | null>(null);
  const cropDone = useRef<((blob: Blob | null) => void) | null>(null);
  const [pageEntry, setPageEntry] = useState<PageSelectEntry | null>(null);
  const pagesDone = useRef<((pages: number[] | null) => void) | null>(null);
  const items = jobs?.items ?? [];
  // P1 empty-filter: q/filter active + total 0 → không được hiện empty-state ("Tải file lên").
  const filtering = q !== "" || filter !== "all";
  // Spec #2: theo dõi transition pending → done/failed của danh sách đang poll.
  useJobDoneToasts(items);
  // Stats + filter tabs are trang hiện tại (server total sống riêng ở stats-total + pagination).
  const visible = filter === "all" ? items : items.filter((j) => j.status === filter);
  const pending = items.filter((j) => PENDING_STATUSES.includes(j.status)).length;
  const done = items.filter((j) => j.status === "done").length;
  // Server page_size hiện về trong response; mock/old-shape thiếu → 10 (default).
  const pageSize = jobs?.page_size ?? 10;
  const totalPages = Math.max(1, Math.ceil((jobs?.total ?? 0) / pageSize));
  // Chỉ job failed được chọn mới gửi retry (spec D: bulk = chạy lại job failed đã chọn).
  const selectedFailed = items.filter((j) => selected.has(j.id) && j.status === "failed");
  const bulkRetry = useMutation({
    mutationFn: () => api.retryJobs(selectedFailed.map((j) => j.id)),
    onSuccess: ({ ok, errors }) => {
      // R59: partial failure → toast tổng hợp đếm (không nuốt các lỗi sau đầu).
      if (ok > 0) toast.success(t("jobs.bulkRetryQueued"));
      if (errors.length > 0) toast.error(t("jobs.bulkRetryErrors", { n: errors.length }));
      setSelected(new Set());
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
  const allVisibleSelected = visible.length > 0 && visible.every((j) => selected.has(j.id));

  // Reuse Dropzone lane: api.uploadJob = presign → PUT ArrayBuffer (XHR progress) → pdf.js đếm trang → POST /api/jobs.
  const submit = async (pdf: Blob, meta: { page_count: number; filename: string }) => {
    setUploadError(null);
    setPercent(0);
    try {
      const choice = choiceRef.current ?? { mode: "layout" as JobMode, output_format: "md" as SubmitFormat };
      await api.uploadJob(pdf, {
        filename: meta.filename,
        mode: choice.mode,
        output_format: choice.output_format,
        onPhase: setPhase,
        onProgress: setPercent,
      });
      // R59: toast + invalidate + navigate về list route.
      toast.success(t("jobs.uploadQueued"));
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      // T6: quota giảm sau khi tạo job thành công → refetch badge
      queryClient.invalidateQueries({ queryKey: ["quota"] });
      navigate("/jobs");
      return true;
    } catch (err) {
      // R51: inline block kept; toast mirrors it (R59). Files giữ lại để gửi lại.
      setUploadError(err instanceof ApiError ? err.detail : t("errors.uploadFailed"));
      toast.error(mapApiError(err));
      return false;
    } finally {
      setPhase("idle");
    }
  };

  return (
    <PageShell>
      <PageHeader
        title={t("jobs.title")}
        subtitle={t("jobs.subtitle")}
        actions={
          <dl className="flex gap-4">
            <div className="text-right">
              <dt className="sr-only">{t("jobs.stats.total")}</dt>
              <dd>
                <Stat testid="stats-total" label={t("jobs.stats.total")} value={String(jobs?.total ?? items.length)} />
              </dd>
            </div>
            <div className="text-right">
              <dt className="sr-only">{t("jobs.stats.pending")}</dt>
              <dd>
                <Stat testid="stats-pending" label={t("jobs.stats.pending")} value={String(pending)} valueClassName="text-warning" />
              </dd>
            </div>
            <div className="text-right">
              <dt className="sr-only">{t("jobs.stats.done")}</dt>
              <dd>
                <Stat testid="stats-done" label={t("jobs.stats.done")} value={String(done)} valueClassName="text-success" />
              </dd>
            </div>
          </dl>
        }
      />

      {/* Toolbar: search + sort + filter tabs — spec #3 (q/sort/status server-side). */}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-1 flex-wrap items-center gap-2">
          <label className="relative min-w-40 flex-1 sm:max-w-xs">
            <span className="sr-only">{t("jobs.searchLabel")}</span>
            <input
              type="search"
              data-testid="jobs-search"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                resetToFirstPage();
              }}
              placeholder={t("jobs.searchPlaceholder")}
              className="h-10 w-full rounded-sm border border-border bg-surface px-3 text-sm text-text placeholder:text-muted focus-visible:outline-2 focus-visible:outline-accent"
            />
          </label>
          <Select
            label={t("jobs.sortLabel")}
            testid="jobs-sort"
            value={sort}
            onChange={(e) => {
              setSort(e.target.value as "newest" | "oldest");
              resetToFirstPage();
            }}
          >
            <option value="newest">{t("jobs.sortNewest")}</option>
            <option value="oldest">{t("jobs.sortOldest")}</option>
          </Select>
        </div>
        <StatusFilterTabs
          items={items}
          value={filter}
          onChange={(v) => {
            setFilter(v);
            resetToFirstPage();
          }}
        />
      </div>

      {/* Spec U3: Gửi → modal mode/format; U1: multi-file cards + crop/page-select. */}
      {denied && (
        <div
          data-testid="banner-no-access"
          className="mb-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-warning"
        >
          {t("jobs.deniedTitle")}
          <p className="mt-1 text-xs">
            {t("jobs.deniedHint")}
          </p>
        </div>
      )}
      {uploadError && (
        <div
          data-testid="upload-error"
          className="mb-2 rounded-md border border-error/40 bg-error/10 px-3 py-2 text-error"
        >
          {uploadError}
        </div>
      )}
      {phase === "uploading" && (
        <div data-testid="upload-progress" className="mb-2 space-y-1">
          <div
            role="progressbar"
            aria-valuenow={percent}
            aria-valuemin={0}
            aria-valuemax={100}
            className="h-2 w-full overflow-hidden rounded-md bg-surface-2"
          >
            <div
              className="h-full rounded-md bg-accent transition-[width] duration-200"
              style={{ width: `${percent}%` }}
            />
          </div>
          <p className="text-xs text-muted">{percent}%</p>
        </div>
      )}
      {phase === "counting" && (
        <p data-testid="upload-counting" className="mb-2 text-sm text-muted">
          {t("jobs.countingPages")}
        </p>
      )}
      <MultiFileUpload
        disabled={denied}
        beforeSubmit={
          () =>
            new Promise<boolean>((res) => {
              submitGate.current = res;
              setModalOpen(true);
            })
        }
        onSubmit={submit}
        onCrop={
          (blob, name) =>
            new Promise<Blob | null>((res) => {
              cropDone.current = res;
              setCrop({ blob, name });
            })
        }
        onSelectPages={
          (entry) =>
            new Promise<number[] | null>((res) => {
              pagesDone.current = res;
              setPageEntry(entry);
            })
        }
      />
      <SubmitModal
        open={modalOpen}
        onConfirm={(choice) => {
          choiceRef.current = choice;
          setModalOpen(false);
          submitGate.current?.(true);
          submitGate.current = null;
        }}
        onCancel={() => {
          setModalOpen(false);
          submitGate.current?.(false);
          submitGate.current = null;
        }}
      />
      {crop && (
        <CropDialog
          blob={crop.blob}
          name={crop.name}
          onCancel={() => {
            cropDone.current?.(null);
            cropDone.current = null;
            setCrop(null);
          }}
          onDone={(b) => {
            cropDone.current?.(b);
            cropDone.current = null;
            setCrop(null);
          }}
        />
      )}
      {pageEntry && (
        <PageSelectDialog
          entry={pageEntry}
          onCancel={() => {
            pagesDone.current?.(null);
            pagesDone.current = null;
            setPageEntry(null);
          }}
          onDone={(pages) => {
            pagesDone.current?.(pages);
            pagesDone.current = null;
            setPageEntry(null);
          }}
        />
      )}

      {/* Phase 4: select-all trang hiện tại — chọn đúng các hàng đang thấy. */}
      {!isLoading && items.length > 0 && (
        <label className="mb-2 inline-flex cursor-pointer items-center gap-2 text-sm text-muted">
          <input
            type="checkbox"
            data-testid="select-all-page"
            checked={allVisibleSelected}
            onChange={() =>
              setSelected(allVisibleSelected ? new Set() : new Set(visible.map((j) => j.id)))
            }
            className="h-4 w-4 accent-accent"
          />
          {t("jobs.selectAll")}
        </label>
      )}

      <div className="mt-6">
        {isLoading ? (
          /* Loading: skeleton rows matching JobRow dimensions (DESIGN.md §4 — no spinners). */
          <ul
            aria-busy="true"
            className="divide-y divide-border rounded-card border border-border bg-surface"
          >
            {[0, 1, 2].map((i) => (
              <li key={i} className="flex items-center justify-between gap-3 px-4 py-3">
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-4 w-1/2" />
                  <Skeleton className="h-3 w-1/3" />
                </div>
                <Skeleton className="h-6 w-24" />
              </li>
            ))}
          </ul>
        ) : jobs && jobs.total === 0 && !filtering ? (
          /* Composed empty state: icon + title + guidance + CTA hint (DESIGN.md §4). */
          <EmptyState
            icon={Inbox}
            title={t("jobs.emptyTitle")}
            body={t("jobs.emptyBody")}
            extra={<p className="mt-1 text-sm text-muted">{t("jobs.emptyWorker")}</p>}
            action={<p className="text-sm font-medium text-accent-text">{t("jobs.emptyCta")}</p>}
            testid="empty-state"
          />
        ) : visible.length === 0 ? (
          <div
            data-testid="empty-filter"
            className="flex items-center gap-2 rounded-card border border-border bg-surface px-4 py-3 text-sm text-muted"
          >
            <Inbox className="h-4 w-4 shrink-0" aria-hidden="true" />
            {t("jobs.emptyFilter")}
          </div>
        ) : (
          <ul className="divide-y divide-border rounded-card border border-border bg-surface">
            {visible.map((job) => (
              <JobRow
                key={job.id}
                job={job}
                selected={selected.has(job.id)}
                onToggle={(id) =>
                  setSelected((prev) => {
                    const next = new Set(prev);
                    if (next.has(id)) next.delete(id);
                    else next.add(id);
                    return next;
                  })
                }
              />
            ))}
          </ul>
        )}
      </div>

      {/* Phase 4: phân trang server-side — Trước/Sau + số trang (10 job/trang). */}
      {!isLoading && (jobs?.total ?? 0) > pageSize && (
        <Pagination
          page={page}
          totalPages={totalPages}
          onChange={changePage}
          prevTestid="btn-page-prev"
          nextTestid="btn-page-next"
          pageTestid="btn-page"
          numbers
          navTestid="pagination"
          ariaLabel={t("jobs.paginationAria")}
          prevLabel={t("jobs.prev")}
          nextLabel={t("jobs.next")}
        />
      )}

      {/* Phase 4: bulk bar sticky bottom khi có chọn (R59: toast mọi mutation). */}
      {selected.size > 0 && (
        <div
          data-testid="bulk-bar"
          className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-surface/95 backdrop-blur"
        >
          <div className="mx-auto flex max-w-3xl items-center justify-between gap-3 px-4 py-3 sm:px-6">
            <span data-testid="bulk-count" className="text-sm font-medium text-text">
              {t("jobs.selectedCount", { n: selected.size })}
            </span>
            <Button
              testid="bulk-retry"
              size="sm"
              variant="primary"
              disabled={bulkRetry.isPending || selectedFailed.length === 0}
              onClick={() => bulkRetry.mutate()}
            >
              {t("jobs.retrySelected")}
            </Button>
          </div>
        </div>
      )}
      {selected.size > 0 && <div aria-hidden="true" className="h-16" />}
    </PageShell>
  );
}
