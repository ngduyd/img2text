import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { api } from "../api/client";
import type { RegionOut } from "../api/types";
import { VERDICT_LABELS } from "../lib/verdicts";
import RegionEditor from "./RegionEditor";
import Button from "./ui/Button";

/**
 * Signed R2 crop URL, cached per region; staleTime Infinity → no refetch.
 * WS-UI crop404: chỉ fetch khi file_type == "image" (PDF không có crop
 * artifact → 404 spam); retry:false — một lần fail là dừng.
 */
function Crop({ jobId, rid, fileType }: { jobId: string; rid: string; fileType: string }) {
  const { data } = useQuery({
    queryKey: ["crop", jobId, rid],
    queryFn: () => api.getCropUrl(jobId, rid),
    enabled: fileType === "image",
    retry: false,
    staleTime: Infinity,
  });
  if (!data) return null;
  return (
    <img
      data-testid={`crop-${rid}`}
      src={data.url}
      alt={`Cắt vùng ${rid}`}
      className="mt-1 max-w-40 rounded-md"
    />
  );
}

/**
 * Task 6 rows + Task 2 inline region edit: one row per region where
 * verdict !== "ok" (edit button hidden for ok — ok rows are not rendered).
 * JD2: accordion collapse (document-first) — rows luôn trong DOM, ẩn bằng
 * hidden; toggle issues-toggle mở/đóng. Local text overrides win over the
 * query prop until refetch replaces them.
 */
export default function IssuesPanel({
  jobId,
  regions,
  fileType,
  onRegionUpdated,
}: {
  jobId: string;
  regions: RegionOut[];
  fileType: string;
  onRegionUpdated?: (rid: string, text: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [activeRid, setActiveRid] = useState<string | null>(null);
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [replacedNotes, setReplacedNotes] = useState<Record<string, boolean>>({});

  const issues = regions
    .filter((r) => r.verdict !== "ok")
    .map((r) => (overrides[r.id] !== undefined ? { ...r, text: overrides[r.id] } : r));

  return (
    <section className="border-t border-border pt-4">
      <h2 className="text-sm font-semibold">
        <button
          type="button"
          data-testid="issues-toggle"
          aria-expanded={open}
          aria-controls="issues-list"
          onClick={() => setOpen((o) => !o)}
          className="flex w-full cursor-pointer items-center justify-between gap-2 rounded-md px-2 py-1 text-left transition duration-150 ease-out hover:bg-surface-2"
        >
          Vấn đề ({issues.length})
          <ChevronDown
            className={`h-4 w-4 text-muted transition duration-150 ease-out ${open ? "rotate-180" : ""}`}
            aria-hidden="true"
          />
        </button>
      </h2>
      <div
        id="issues-list"
        data-testid="issues-list"
        hidden={!open}
        className="mt-1 max-w-[75ch] divide-y divide-border leading-[1.6]"
      >
        {issues.map((r) => (
          <article key={r.id} data-testid={`issue-${r.id}`} className="py-2">
            <span className="font-semibold">{VERDICT_LABELS[r.verdict] ?? r.verdict}</span>{" "}
            <span className="text-sm text-muted">{r.id}</span>
            {/* PDF → text region (dưới), không crop image. */}
            {r.bbox != null && fileType === "image" && (
              <Crop jobId={jobId} rid={r.id} fileType={fileType} />
            )}
            {r.text && <p className="text-sm">{r.text}</p>}
            {replacedNotes[r.id] && (
              <p data-testid={`region-note-${r.id}`} className="mt-1 text-sm text-warning">
                Văn bản vùng đã cập nhật; markdown chưa thay thế (text gốc không còn trong bản xem trước)
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
      </div>
    </section>
  );
}
