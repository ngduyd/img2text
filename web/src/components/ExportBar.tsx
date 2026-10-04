import { useState } from "react";
import { ApiError, api } from "../api/client";

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
      if (w) w.location = url;
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Xuất file thất bại.");
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
          className="mb-2 rounded border border-red-300 bg-red-50 px-3 py-2 text-red-700"
        >
          {error}
        </div>
      )}
      <div className="flex gap-2">
        {FORMATS.map(({ fmt, testid, label }) => (
          <button
            key={fmt}
            type="button"
            data-testid={testid}
            disabled={busy.has(fmt)}
            onClick={() => exportFmt(fmt)}
            className="rounded bg-blue-600 px-4 py-2 text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
