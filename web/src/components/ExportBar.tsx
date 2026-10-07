import { useState } from "react";
import { toast } from "sonner";
import { ApiError, api } from "../api/client";
import { mapApiError } from "../lib/errors";
import Button from "./ui/Button";

const FORMATS = [
  { fmt: "md", testid: "export-md", label: "Tải .md" },
  { fmt: "html", testid: "export-html", label: "Tải .html" },
  { fmt: "docx", testid: "export-docx", label: "Tải .docx" },
  // D4 review P2: LLM layout docx (auto-gen key docx-layout; pandoc .docx khác bytes)
  { fmt: "docx-layout", testid: "btn-export-docx-layout", label: "DOCX (giữ layout)" },
  // D5: LLM md-layout (geometry-aware markdown; pandoc .md khác layout)
  { fmt: "md-layout", testid: "btn-export-md-layout", label: "Markdown (layout)" },
  { fmt: "pdf", testid: "export-pdf", label: "Tải .pdf" },
] as const;

type Fmt = (typeof FORMATS)[number]["fmt"];

/** JD2 rail: 1 nút chính (.md) + disclosure "Định dạng khác" (các nút cũ giữ nguyên testid). */
export default function ExportBar({ jobId }: { jobId: string }) {
  const [busy, setBusy] = useState<Set<Fmt>>(() => new Set());
  const [error, setError] = useState<string | null>(null);
  const [more, setMore] = useState(false);

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

  return (
    <div data-testid="export-bar">
      {error && (
        <div
          data-testid="export-error"
          className="mb-2 rounded-md border border-error/40 bg-error/10 px-3 py-2 text-error"
        >
          {error}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button testid="export-md" loading={busy.has("md")} onClick={() => exportFmt("md")}>
          Tải .md
        </Button>
        <Button
          testid="export-more"
          variant="secondary"
          size="sm"
          aria-expanded={more}
          aria-controls="export-formats"
          onClick={() => setMore((v) => !v)}
        >
          Định dạng khác
        </Button>
      </div>
      <div
        id="export-formats"
        data-testid="export-formats"
        hidden={!more}
        className="mt-2 flex flex-wrap gap-2"
      >
        {FORMATS.filter(({ fmt }) => fmt !== "md").map(({ fmt, testid, label }) => (
          <Button
            key={fmt}
            testid={testid}
            variant="secondary"
            loading={busy.has(fmt)}
            onClick={() => exportFmt(fmt)}
          >
            {label}
          </Button>
        ))}
      </div>
    </div>
  );
}
