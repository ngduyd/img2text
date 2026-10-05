import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import type { RegionOut } from "../api/types";
import { VERDICT_LABELS } from "../lib/verdicts";
import RegionEditor from "./RegionEditor";
import Button from "./ui/Button";

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

/**
 * Task 6 rows + Task 2 inline region edit: one row per region where
 * verdict !== "ok" (edit button hidden for ok — ok rows are not rendered).
 * Local text overrides win over the query prop until refetch replaces them.
 */
export default function IssuesPanel({
  jobId,
  regions,
  onRegionUpdated,
}: {
  jobId: string;
  regions: RegionOut[];
  onRegionUpdated?: (rid: string, text: string) => void;
}) {
  const [activeRid, setActiveRid] = useState<string | null>(null);
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [replacedNotes, setReplacedNotes] = useState<Record<string, boolean>>({});

  const issues = regions
    .filter((r) => r.verdict !== "ok")
    .map((r) => (overrides[r.id] !== undefined ? { ...r, text: overrides[r.id] } : r));

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
          {replacedNotes[r.id] && (
            <p data-testid={`region-note-${r.id}`} className="mt-1 text-sm text-warning">
              Văn bản vùng đã cập nhật; markdown chưa thay thế (text gốc không còn trong bản xem
              trước)
            </p>
          )}
          {activeRid === r.id ? (
            <RegionEditor
              jobId={jobId}
              region={r}
              onSaved={(rid, text, markdownReplaced) => {
                setOverrides((prev) => ({ ...prev, [rid]: text }));
                setReplacedNotes((prev) => ({ ...prev, [rid]: markdownReplaced === false }));
                setActiveRid(null);
                onRegionUpdated?.(rid, text);
              }}
              onCancel={() => setActiveRid(null)}
            />
          ) : (
            <div className="mt-1">
              <Button
                testid={`btn-edit-region-${r.id}`}
                variant="secondary"
                size="sm"
                onClick={() => setActiveRid(r.id)}
              >
                Sửa vùng
              </Button>
            </div>
          )}
        </article>
      ))}
    </section>
  );
}
