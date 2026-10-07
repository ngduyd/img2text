import DOMPurify from "dompurify";
import * as mammoth from "mammoth";
import { marked } from "marked";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { ApiError, api } from "../api/client";
import { mapApiError } from "../lib/errors";
import DocStyleTools from "./DocStyleTools";
import Button from "./ui/Button";
import Card from "./ui/Card";

const DOC_PREFIX = "<!doctype html><meta charset=\"utf-8\">";

/**
 * Task 5: export preview tabs (md/docx). Plan JD drops the PDF preview tab —
 * PDF export stays in ExportBar. DOCX lazy on first activation.
 */
const TABS = [
  { tab: "md", testid: "preview-md", label: "Markdown" },
  { tab: "docx", testid: "preview-docx", label: "DOCX" },
] as const;

type Tab = (typeof TABS)[number]["tab"];
type LlmFmt = "md-layout" | "docx-layout";

/** Chèn style tag vào HTML đã sanitize — không đụng nội dung gốc (WordTool pattern). */
function withStyle(html: string, css: string): string {
  const tag = `<style>${css}</style>`;
  if (/<head[^>]*>/i.test(html)) return html.replace(/<head[^>]*>/i, (m) => `${m}${tag}`);
  return tag + html;
}

export default function PreviewTabs({
  jobId,
  markdown,
}: {
  jobId: string;
  markdown: string;
}) {
  const [tab, setTab] = useState<Tab>("md");
  const [mdText, setMdText] = useState(markdown);
  // Editor save → new markdown prop wins over an LLM override (adjust during render;
  // React-sanctioned pattern, avoids set-state-in-effect).
  const [mdSource, setMdSource] = useState(markdown);
  if (markdown !== mdSource) {
    setMdSource(markdown);
    setMdText(markdown);
  }
  // Sanitized mammoth HTML; DocStyleTools CSS is injected at render time.
  const [docxHtml, setDocxHtml] = useState<string | null>(null);
  const [css, setCss] = useState("");
  const [error, setError] = useState<string | null>(null);

  // md preview rendered here (not MarkdownPreview) so DocStyleTools CSS can inject —
  // same sanitize contract: marked → DOMPurify → sandboxed srcdoc (testid preview-markdown).
  const mdSrcDoc = useMemo(
    () =>
      DOC_PREFIX +
      (css ? `<style>${css}</style>` : "") +
      DOMPurify.sanitize(marked.parse(mdText) as string),
    [mdText, css],
  );

  // State cache: reactivation must not re-call exportJob (brief, verbatim).
  const activate = (t: Tab) => {
    setTab(t);
    setError(null);
    if (t === "docx" && docxHtml === null) void loadDocx();
  };

  const loadDocx = async () => {
    try {
      await api.exportJob(jobId, "docx");
      const blob = await api.downloadExport(jobId, "docx");
      toast.success("Đã tạo bản xuất.");
      const { value } = await mammoth.convertToHtml({
        arrayBuffer: await blob.arrayBuffer(),
      });
      // mammoth output untrusted → DOMPurify before srcdoc (script stripped)
      setDocxHtml(DOMPurify.sanitize(value));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Xem trước thất bại.");
      toast.error(mapApiError(err));
    }
  };

  /** Plan JD: LLM re-layout → export + blob download → preview content (md text / docx pipeline). */
  const runLlmLayout = async (fmt: LlmFmt) => {
    const loadingId = toast.loading("Đang gọi LLM…");
    try {
      await api.exportJob(jobId, fmt);
      const blob = await api.downloadExport(jobId, fmt);
      if (fmt === "md-layout") {
        setMdText(await blob.text());
      } else {
        const { value } = await mammoth.convertToHtml({
          arrayBuffer: await blob.arrayBuffer(),
        });
        setDocxHtml(DOMPurify.sanitize(value));
      }
      toast.success("Đã cập nhật layout (LLM).", { id: loadingId });
    } catch (err) {
      toast.dismiss(loadingId);
      toast.error(mapApiError(err));
    }
  };

  return (
    <Card testid="panel-docs" title="Tài liệu">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex gap-2">
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
        <Button
          testid={tab === "md" ? "btn-llm-layout-md" : "btn-llm-layout-docx"}
          variant="secondary"
          size="sm"
          onClick={() => void runLlmLayout(tab === "md" ? "md-layout" : "docx-layout")}
        >
          Chỉnh layout bằng LLM
        </Button>
      </div>
      {error && (
        <div
          data-testid="docs-error"
          className="mb-2 rounded-md border border-error/40 bg-error/10 px-3 py-2 text-error"
        >
          {error}
        </div>
      )}
      {tab === "md" && (
        <iframe
          data-testid="preview-markdown"
          sandbox=""
          title="Xem trước Markdown"
          srcDoc={mdSrcDoc}
          className="h-96 w-full rounded-md border border-border"
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
              srcDoc={withStyle(docxHtml, css)}
              className="h-96 w-full rounded-md border border-border"
            />
          )}
        </>
      )}
      <DocStyleTools onChange={setCss} />
    </Card>
  );
}
