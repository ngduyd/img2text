import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import Dropzone from "../components/Dropzone";
import JobRow from "../components/JobRow";
import StatusFilterTabs from "../components/StatusFilterTabs";
import type { StatusFilter } from "../components/StatusFilterTabs";
import Card from "../components/ui/Card";

export default function Jobs() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: jobs } = useQuery({ queryKey: ["jobs"], queryFn: api.listJobs });
  const [filter, setFilter] = useState<StatusFilter>("all");
  const items = jobs?.items ?? [];
  const visible = filter === "all" ? items : items.filter((j) => j.status === filter);

  return (
    <main id="main" className="mx-auto max-w-3xl p-4">
      <h1 className="mb-4 text-xl font-bold">Công việc</h1>
      {/* R59: file list lives at "/" — invalidate so the new job shows without a remount. */}
      <Dropzone
        onUploaded={() => {
          queryClient.invalidateQueries({ queryKey: ["jobs"] });
          navigate("/");
        }}
      />
      {jobs !== undefined && items.length === 0 ? (
        <Card testid="empty-state" title="Chưa có công việc">
          <p className="text-sm text-muted">
            Tải ảnh trang sách hoặc file PDF để bắt đầu OCR. Mỗi job xử lý tối đa 50 trang · 50MB.
          </p>
          <p className="mt-2 text-sm text-muted">Job chờ worker Colab kết nối.</p>
        </Card>
      ) : (
        <>
          <div className="mt-4">
            <StatusFilterTabs items={items} value={filter} onChange={setFilter} />
          </div>
          {visible.length === 0 ? (
            <p
              data-testid="empty-filter"
              className="mt-4 rounded-card border border-border bg-surface px-4 py-3 text-sm text-muted"
            >
              Không có công việc nào khớp bộ lọc.
            </p>
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
