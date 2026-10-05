import DOMPurify from "dompurify";
import * as mammoth from "mammoth";
import { useState } from "react";
import { ApiError, api } from "../api/client";
import MarkdownPreview from "./MarkdownPreview";
import Button from "./ui/Button";
import Card from "./ui/Card";

/** Task 5: export preview tabs (md/pdf/docx). PDF/DOCX lazy on first activation. */
const TABS = [
  { tab: "md", testid: "preview-md", label: "Markdown" },
  { tab: "pdf", testid: "preview-pdf", label: "PDF" },
  { tab: "docx", testid: "preview-docx", label: "DOCX" },
] as const;

type Tab = (typeof TABS)[number]["tab"];

export default function PreviewTabs({
  jobId,
  markdown,
}: {
  jobId: string;
  markdown: string;
}) {
  const [tab, setTab] = useState<Tab>("md");
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [docxHtml, setDocxHtml] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // State cache: reactivation must not re-call exportJob (brief, verbatim).
  const activate = (t: Tab) => {
    setTab(t);
    setError(null);
    if (t === "pdf" && pdfUrl === null) void loadPdf();
    if (t === "docx" && docxHtml === null) void loadDocx();
  };

  const loadPdf = async () => {
    try {
      const { url } = await api.exportJob(jobId, "pdf");
      setPdfUrl(url);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Xem trước thất bại.");
    }
  };

  const loadDocx = async () => {
    try {
      await api.exportJob(jobId, "docx");
      const blob = await api.downloadExport(jobId, "docx");
      const { value } = await mammoth.convertToHtml({
        arrayBuffer: await blob.arrayBuffer(),
      });
      // mammoth output untrusted → DOMPurify before srcdoc (script stripped)
      setDocxHtml(DOMPurify.sanitize(value));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Xem trước thất bại.");
    }
  };

  return (
    <Card testid="panel-docs" title="Tài liệu">
      <div className="mb-3 flex gap-2">
        {TABS.map(({ tab: t, testid, label }) => (
          <Button
            key={t}
            testid={testid}
            variant="ghost"
            aria-pressed={tab === t}
            className={tab === t ? "bg-surface font-semibold" : ""}
            onClick={() => activate(t)}
          >
            {label}
          </Button>
        ))}
      </div>
      {error && (
        <div
          data-testid="docs-error"
          className="mb-2 rounded-lg border border-error/40 bg-error/10 px-3 py-2 text-error"
        >
          {error}
        </div>
      )}
      {tab === "md" && <MarkdownPreview markdown={markdown} />}
      {tab === "pdf" && pdfUrl && (
        <iframe
          data-testid="preview-pdf-frame"
          src={pdfUrl}
          title="Xem trước PDF"
          className="h-96 w-full rounded-lg border border-border"
        />
      )}
      {tab === "docx" && (
        <>
          <p data-testid="docx-note" className="mb-2 text-sm text-muted">
            Xem trước DOCX: giữ nội dung, mất định dạng font.
          </p>
          {docxHtml !== null && (
            <iframe
              data-testid="preview-docx-frame"
              sandbox=""
              title="Xem trước DOCX"
              srcDoc={docxHtml}
              className="h-96 w-full rounded-lg border border-border"
            />
          )}
        </>
      )}
    </Card>
  );
}
