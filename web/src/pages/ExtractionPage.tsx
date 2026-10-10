import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import Skeleton from "../components/ui/Skeleton";

/**
 * Phase 2 (spec Sub-system B): trang trích xuất văn bản gốc.
 * Render text gốc + highlight từ lỗi (proofread suggestions) — Task 3.
 */
export default function ExtractionPage() {
  const { id } = useParams<{ id: string }>();
  const { data, isPending, isError } = useQuery({
    queryKey: ["extraction", id],
    queryFn: () => api.getExtraction(id!),
  });

  return (
    <main id="main" className="mx-auto max-w-4xl p-4 sm:p-6">
      <header
        data-testid="extraction-header"
        className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2"
      >
        <Link
          to={`/jobs/${id}`}
          data-testid="link-back-job"
          className="inline-flex items-center gap-1 text-sm text-accent-text transition duration-150 ease-out hover:underline"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          Về chi tiết công việc
        </Link>
        <h1 className="text-xl font-bold tracking-tight sm:text-2xl">
          Trích xuất văn bản <span className="font-mono">#{id}</span>
        </h1>
      </header>

      {isPending && (
        <div data-testid="extraction-loading" className="flex flex-col gap-3">
          <Skeleton className="h-8 w-2/3" />
          <Skeleton className="h-24 w-full" />
        </div>
      )}
      {isError && (
        <p data-testid="extraction-error" role="alert" className="text-sm text-error">
          Không tải được văn bản trích xuất.
        </p>
      )}
      {data && (
        <article
          data-testid="extraction-text"
          data-text-version={data.text_version}
          className="rounded-card border border-border bg-surface p-4 text-sm leading-[1.7] whitespace-pre-wrap shadow-card"
        >
          {data.text}
        </article>
      )}
    </main>
  );
}
