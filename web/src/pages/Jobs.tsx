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
  const items = jobs?.items ?? [];
  const visible = filter === "all" ? items : items.filter((j) => j.status === filter);

  return (
    <main id="main" className="mx-auto max-w-3xl p-4 sm:p-6">
      <h1 className="mb-6 text-2xl font-bold tracking-tight">Công việc</h1>
      {/* R59: invalidate so the new job shows; navigate to the /jobs list route. */}
      <Dropzone
        onUploaded={() => {
          queryClient.invalidateQueries({ queryKey: ["jobs"] });
          navigate("/jobs");
        }}
      />
      {isLoading ? (
        /* Loading: skeleton rows matching JobRow dimensions (DESIGN.md §4 — no spinners). */
        <ul
          aria-busy="true"
          className="mt-6 divide-y divide-border rounded-card border border-border bg-surface"
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
      ) : jobs !== undefined && items.length === 0 ? (
        <Card testid="empty-state" title="Chưa có công việc">
          <div className="flex items-start gap-3">
            <Inbox className="mt-0.5 h-5 w-5 shrink-0 text-muted" aria-hidden="true" />
            <div>
              <p className="text-sm text-muted">
                Tải ảnh trang sách hoặc file PDF để bắt đầu OCR. Mỗi job xử lý tối đa 50 trang ·
                50MB.
              </p>
              <p className="mt-2 text-sm text-muted">Job chờ worker Colab kết nối.</p>
            </div>
          </div>
        </Card>
      ) : (
        <>
          <div className="mt-6">
            <StatusFilterTabs items={items} value={filter} onChange={setFilter} />
          </div>
          {visible.length === 0 ? (
            <div
              data-testid="empty-filter"
              className="mt-2 flex items-center gap-2 rounded-card border border-border bg-surface px-4 py-3 text-sm text-muted"
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
        </>
      )}
    </main>
  );
}
