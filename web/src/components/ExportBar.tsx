import { useState } from "react";
import { toast } from "sonner";
import { ApiError, api } from "../api/client";
import { mapApiError } from "../lib/errors";
import Button from "./ui/Button";

/**
 * WS-UI item 13 (B) → Lane I Task 5: download text (md|html|docx|pdf) dời lên
 * header dropdown "Tải xuống" (btn-download); ExportBar dưới chỉ giữ nhóm
 * export "Layout" (md-layout | docx-layout, bản dựng layout).
 * R51 testids cũ giữ nguyên (btn-export-md-layout/btn-export-docx-layout/...).
 */
const LAYOUT_FORMATS = [
  { fmt: "md-layout", testid: "btn-export-md-layout", label: "Markdown (layout)" },
  { fmt: "docx-layout", testid: "btn-export-docx-layout", label: "DOCX (giữ layout)" },
] as const;

type Fmt = (typeof LAYOUT_FORMATS)[number]["fmt"];

export default function ExportBar({ jobId }: { jobId: string }) {
  const [busy, setBusy] = useState<Set<Fmt>>(() => new Set());
  const [error, setError] = useState<string | null>(null);
  const [layoutMore, setLayoutMore] = useState(false);

  const exportFmt = async (fmt: Fmt) => {
    setBusy((prev) => new Set(prev).add(fmt));
    setError(null);
    const w = window.open("", "_blank");
    try {
      const { url } = await api.exportJob(jobId, fmt);
      toast.success("Đã tạo bản xuất.");
      if (w) w.location = url;
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Xuất file thất bại.");
      toast.error(mapApiError(err));
    } finally {
      setBusy((prev) => {
        const next = new Set(prev);
        next.delete(fmt);
        return next;
      });
    }
  };

  const renderGroup = (
    label: string,
    open: boolean,
    setOpen: (v: boolean) => void,
    formats: ReadonlyArray<{ fmt: Fmt; testid: string; label: string }>,
    moreTestid: string,
    listTestid: string,
  ) => (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        testid={moreTestid}
        variant="secondary"
        aria-expanded={open}
        aria-controls={listTestid}
        onClick={() => setOpen(!open)}
      >
        {label}
      </Button>
      <div
        id={listTestid}
        data-testid={listTestid}
        hidden={!open}
        className="flex flex-wrap gap-2"
      >
        {formats.map(({ fmt, testid, label: fmtLabel }) => (
          <Button
            key={fmt}
            testid={testid}
            variant="secondary"
            loading={busy.has(fmt)}
            onClick={() => exportFmt(fmt)}
          >
            {fmtLabel}
          </Button>
        ))}
      </div>
    </div>
  );

  return (
    <div data-testid="export-bar" className="flex flex-col gap-2">
      {error && (
        <div
          data-testid="export-error"
          className="rounded-md border border-error/40 bg-error/10 px-3 py-2 text-error"
        >
          {error}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {renderGroup(
          "Layout",
          layoutMore,
          setLayoutMore,
          LAYOUT_FORMATS,
          "export-layout-more",
          "export-layout-formats",
        )}
      </div>
    </div>
  );
}
