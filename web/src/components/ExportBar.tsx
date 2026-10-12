import { useState } from "react";
import { toast } from "sonner";
import { ApiError, api } from "../api/client";
import { mapApiError } from "../lib/errors";
import Button from "./ui/Button";

/**
 * WS-UI item 13 (B): 2 nhóm dropdown — "Văn bản" (md | html | docx | pdf,
 * export thuần text) và "Layout" (md-layout | docx-layout, bản dựng layout).
 * R51 testids cũ giữ nguyên (export-md/export-more/export-formats/...).
 */
const TEXT_FORMATS = [
  { fmt: "md", testid: "export-md", label: "Tải .md" },
  { fmt: "html", testid: "export-html", label: "Tải .html" },
  { fmt: "docx", testid: "export-docx", label: "Tải .docx" },
  { fmt: "pdf", testid: "export-pdf", label: "Tải .pdf" },
] as const;

const LAYOUT_FORMATS = [
  { fmt: "md-layout", testid: "btn-export-md-layout", label: "Markdown (layout)" },
  { fmt: "docx-layout", testid: "btn-export-docx-layout", label: "DOCX (giữ layout)" },
] as const;

type Fmt = (typeof TEXT_FORMATS)[number]["fmt"] | (typeof LAYOUT_FORMATS)[number]["fmt"];

export default function ExportBar({ jobId }: { jobId: string }) {
  const [busy, setBusy] = useState<Set<Fmt>>(() => new Set());
  const [error, setError] = useState<string | null>(null);
  const [textMore, setTextMore] = useState(false);
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
    group: "text" | "layout",
    open: boolean,
    setOpen: (v: boolean) => void,
    formats: ReadonlyArray<{ fmt: Fmt; testid: string; label: string }>,
    moreTestid: string,
    listTestid: string,
  ) => (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        testid={moreTestid}
        variant={group === "text" ? "primary" : "secondary"}
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
          "Văn bản",
          "text",
          textMore,
          setTextMore,
          TEXT_FORMATS,
          "export-more",
          "export-formats",
        )}
        {renderGroup(
          "Layout",
          "layout",
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
