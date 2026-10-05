import { useState } from "react";
import { toast } from "sonner";
import { ApiError, api } from "../api/client";
import { mapApiError } from "../lib/errors";
import Button from "./ui/Button";

const FORMATS = [
  { fmt: "md", testid: "export-md", label: "Tải .md" },
  { fmt: "html", testid: "export-html", label: "Tải .html" },
  { fmt: "docx", testid: "export-docx", label: "Tải .docx" },
  { fmt: "pdf", testid: "export-pdf", label: "Tải .pdf" },
] as const;

type Fmt = (typeof FORMATS)[number]["fmt"];

export default function ExportBar({ jobId }: { jobId: string }) {
  const [busy, setBusy] = useState<Set<Fmt>>(() => new Set());
  const [error, setError] = useState<string | null>(null);

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
    <div>
      {error && (
        <div
          data-testid="export-error"
          className="mb-2 rounded-lg border border-error/40 bg-error/10 px-3 py-2 text-error"
        >
          {error}
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        {FORMATS.map(({ fmt, testid, label }) => (
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
