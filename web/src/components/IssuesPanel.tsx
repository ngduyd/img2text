import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { RegionOut } from "../api/types";
import { VERDICT_LABELS } from "../lib/verdicts";

/** Signed R2 crop URL, cached per region; staleTime Infinity → no refetch. */
function Crop({ jobId, rid }: { jobId: string; rid: string }) {
  const { data } = useQuery({
    queryKey: ["crop", jobId, rid],
    queryFn: () => api.getCropUrl(jobId, rid),
    staleTime: Infinity,
  });
  if (!data) return null;
  return <img data-testid={`crop-${rid}`} src={data.url} alt={`Cắt vùng ${rid}`} />;
}

/** Task 6: one row per region where verdict !== "ok" (label, id, crop, vlm excerpt). */
export default function IssuesPanel({ jobId, regions }: { jobId: string; regions: RegionOut[] }) {
  const issues = regions.filter((r) => r.verdict !== "ok");
  return (
    <section className="mt-4">
      <h2 className="mb-2 text-lg font-bold">Vấn đề ({issues.length})</h2>
      {issues.map((r) => (
        <article
          key={r.id}
          data-testid={`issue-${r.id}`}
          className="mb-2 rounded-card border border-border p-2"
        >
          <span className="font-semibold">{VERDICT_LABELS[r.verdict] ?? r.verdict}</span>{" "}
          <span className="text-sm text-muted">{r.id}</span>
          {r.bbox != null && <Crop jobId={jobId} rid={r.id} />}
          {r.text && <p className="text-sm">{r.text}</p>}
        </article>
      ))}
    </section>
  );
}
