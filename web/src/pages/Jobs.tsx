import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Inbox } from "lucide-react";
import { api } from "../api/client";
import Dropzone from "../components/Dropzone";
import JobRow from "../components/JobRow";
import StatusFilterTabs from "../components/StatusFilterTabs";
import type { StatusFilter } from "../components/StatusFilterTabs";
import Card from "../components/ui/Card";
import Skeleton from "../components/ui/Skeleton";

export default function Jobs() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: jobs, isLoading } = useQuery({ queryKey: ["jobs"], queryFn: api.listJobs });
  const [filter, setFilter] = useState<StatusFilter>("all");
  // Plan D4: export format chosen BEFORE upload — stored on the job, auto-generated after OCR.
  const [outputFormat, setOutputFormat] = useState<"md" | "docx">("md");
  const items = jobs?.items ?? [];
  const visible = filter === "all" ? items : items.filter((j) => j.status === filter);
  const pending = items.filter((j) => j.status === "queued" || j.status === "running").length;
  const done = items.filter((j) => j.status === "done").length;

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
              {items.length}
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

      {/* Toolbar: format select left, filter tabs right — single wrapped row. */}
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <label htmlFor="output-format" className="text-sm text-muted">
            Đầu ra
          </label>
          <select
            id="output-format"
            data-testid="select-output-format"
            value={outputFormat}
            onChange={(e) => setOutputFormat(e.target.value as "md" | "docx")}
            className="rounded-sm border border-border bg-surface px-2 py-1 text-sm focus-visible:outline-2 focus-visible:outline-accent"
          >
            <option value="md">Markdown</option>
            <option value="docx">Word (.docx)</option>
          </select>
        </div>
        <StatusFilterTabs items={items} value={filter} onChange={setFilter} />
      </div>

      {/* R59: invalidate so the new job shows; navigate to the /jobs list route. */}
      <Dropzone
        outputFormat={outputFormat}
        onUploaded={() => {
          queryClient.invalidateQueries({ queryKey: ["jobs"] });
          navigate("/jobs");
        }}
      />

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
        ) : items.length === 0 ? (
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
              <JobRow key={job.id} job={job} />
            ))}
          </ul>
        )}
      </div>
    </main>
  );
}
