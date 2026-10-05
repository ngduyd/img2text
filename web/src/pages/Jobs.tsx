import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import StatusBadge from "../components/StatusBadge";
import UploadButton from "../components/UploadButton";

export default function Jobs() {
  const navigate = useNavigate();
  const { data: jobs } = useQuery({ queryKey: ["jobs"], queryFn: api.listJobs });

  return (
    <main id="main" className="mx-auto max-w-3xl p-4">
      <h1 className="mb-4 text-xl font-bold">Công việc</h1>
      <UploadButton onUploaded={(job) => navigate(`/jobs/${job.id}`)} />
      <ul className="mt-4 divide-y divide-border rounded-card border border-border bg-surface">
        {(jobs?.items ?? []).map((job) => (
          <li
            key={job.id}
            data-testid={`job-row-${job.id}`}
            className="flex items-center justify-between px-4 py-3"
          >
            <span>
              #{job.id} · {job.file_type} · {job.page_count} trang
            </span>
            <StatusBadge job={job} />
          </li>
        ))}
      </ul>
    </main>
  );
}
