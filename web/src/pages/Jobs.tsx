import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Inbox } from "lucide-react";
import { toast } from "sonner";
import { api } from "../api/client";
import Dropzone from "../components/Dropzone";
import JobRow from "../components/JobRow";
import StatusFilterTabs from "../components/StatusFilterTabs";
import type { StatusFilter } from "../components/StatusFilterTabs";
import Card from "../components/ui/Card";
import Button from "../components/ui/Button";
import Skeleton from "../components/ui/Skeleton";
import { PENDING_STATUSES } from "../lib/status";

export default function Jobs() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  // Phase 4: server-side page state — mỗi trang 10 job (mặc định server).
  const [page, setPage] = useState(1);
  // Phase 4: selection cho bulk retry — đổi trang → reset (chọn chỉ sống trong trang hiện tại).
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const changePage = (next: number) => {
    setSelected(new Set());
    setPage(next);
  };
  const { data: jobs, isLoading } = useQuery({
    queryKey: ["jobs", page],
    queryFn: () => api.listJobs(page),
  });
  const [filter, setFilter] = useState<StatusFilter>("all");
  // Plan D4: export format chosen BEFORE upload — stored on the job, auto-generated after OCR.
  const [outputFormat, setOutputFormat] = useState<"md" | "docx">("md");
  const items = jobs?.items ?? [];
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
      // R59: partial failure → toast lỗi (batch đã settle các job còn lại).
      if (ok > 0) toast.success("Đã lên lịch chạy lại");
      if (errors.length > 0) toast.error(errors[0]);
      setSelected(new Set());
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
  });
  const allVisibleSelected = visible.length > 0 && visible.every((j) => selected.has(j.id));

  return (
    <main id="main" className="mx-auto max-w-3xl p-4 sm:p-6">
      {/* Asymmetric header: title + subtitle left, stats right (DESIGN.md §5). */}
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Công việc</h1>
          <p className="mt-1 text-sm text-muted">Theo dõi tiến trình OCR trên worker Colab.</p>
        </div>
        <dl className="flex gap-4">
          <div className="text-right">
            <dt className="text-xs text-muted">Tổng</dt>
            <dd data-testid="stats-total" className="font-mono text-lg font-semibold leading-tight">
              {jobs?.total ?? items.length}
            </dd>
          </div>
          <div className="text-right">
            <dt className="text-xs text-muted">Đang chờ</dt>
            <dd
              data-testid="stats-pending"
              className="font-mono text-lg font-semibold leading-tight text-warning"
            >
              {pending}
            </dd>
          </div>
          <div className="text-right">
            <dt className="text-xs text-muted">Hoàn tất</dt>
            <dd
              data-testid="stats-done"
              className="font-mono text-lg font-semibold leading-tight text-success"
            >
              {done}
            </dd>
          </div>
        </dl>
      </header>

      {/* Toolbar: filter tabs — the format picker moved into the upload split button. */}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <StatusFilterTabs items={items} value={filter} onChange={setFilter} />
      </div>

      {/* R59: invalidate so the new job shows; navigate to the /jobs list route. */}
      <Dropzone
        outputFormat={outputFormat}
        onFormatChange={setOutputFormat}
        onUploaded={() => {
          queryClient.invalidateQueries({ queryKey: ["jobs"] });
          navigate("/jobs");
        }}
      />

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
          Chọn cả trang
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
        ) : jobs && jobs.total === 0 ? (
          /* Composed empty state: icon + title + guidance + CTA hint (DESIGN.md §4). */
          <Card testid="empty-state">
            <div className="flex flex-col items-center px-2 py-6 text-center">
              <Inbox className="h-10 w-10 text-muted" aria-hidden="true" />
              <h2 className="mt-3 text-base font-semibold">Chưa có công việc</h2>
              <p className="mt-1 max-w-sm text-sm text-muted">
                Tải ảnh trang sách hoặc file PDF để bắt đầu OCR. Mỗi job xử lý tối đa 50 trang ·
                50MB.
              </p>
              <p className="mt-1 text-sm text-muted">Job chờ worker Colab kết nối.</p>
              <p className="mt-4 text-sm font-medium text-accent-text">
                Tải file lên để tạo công việc đầu tiên.
              </p>
            </div>
          </Card>
        ) : visible.length === 0 ? (
          <div
            data-testid="empty-filter"
            className="flex items-center gap-2 rounded-card border border-border bg-surface px-4 py-3 text-sm text-muted"
          >
            <Inbox className="h-4 w-4 shrink-0" aria-hidden="true" />
            Không có công việc nào khớp bộ lọc.
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
        <nav
          data-testid="pagination"
          aria-label="Phân trang"
          className="mt-4 flex flex-wrap items-center justify-center gap-2"
        >
          <Button
            testid="btn-page-prev"
            size="sm"
            variant="secondary"
            disabled={page <= 1}
            onClick={() => changePage(page - 1)}
          >
            Trước
          </Button>
          {/* ponytail: list mọi số trang — nâng cấp khi total_pages > ~20 (windowed numbers). */}
          {Array.from({ length: totalPages }, (_, i) => i + 1).map((n) => (
            <Button
              key={n}
              testid={`btn-page-${n}`}
              size="sm"
              variant={n === page ? "primary" : "ghost"}
              aria-current={n === page ? "page" : undefined}
              onClick={() => changePage(n)}
            >
              {n}
            </Button>
          ))}
          <Button
            testid="btn-page-next"
            size="sm"
            variant="secondary"
            disabled={page >= totalPages}
            onClick={() => changePage(page + 1)}
          >
            Sau
          </Button>
        </nav>
      )}

      {/* Phase 4: bulk bar sticky bottom khi có chọn (R59: toast mọi mutation). */}
      {selected.size > 0 && (
        <div
          data-testid="bulk-bar"
          className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-surface/95 backdrop-blur"
        >
          <div className="mx-auto flex max-w-3xl items-center justify-between gap-3 px-4 py-3 sm:px-6">
            <span data-testid="bulk-count" className="text-sm font-medium text-text">
              {selected.size} đã chọn
            </span>
            <Button
              testid="bulk-retry"
              size="sm"
              variant="primary"
              disabled={bulkRetry.isPending || selectedFailed.length === 0}
              onClick={() => bulkRetry.mutate()}
            >
              Chạy lại đã chọn
            </Button>
          </div>
        </div>
      )}
    </main>
  );
}
