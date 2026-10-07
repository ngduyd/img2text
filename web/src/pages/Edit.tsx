import DOMPurify from "dompurify";
import { BarChart3, FileText } from "lucide-react";
import * as mammoth from "mammoth";
import { useEffect, useMemo, useRef, useState, type ChangeEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { api } from "../api/client";
import { mapApiError } from "../lib/errors";
import DocStyleTools from "../components/DocStyleTools";
import MarkdownPreview from "../components/MarkdownPreview";
import Button from "../components/ui/Button";
import Card from "../components/ui/Card";
import { DEFAULT_PREVIEW_OPTS, buildPreviewCss, withStyle } from "../lib/docStyle";
import { renderMarkdown } from "../lib/markdown";

const EMPTY_TITLE = "Chưa có tài liệu";

/** Stats từ HTML parse — count h1/h2/h3/table/đoạn (p) — chỉ pane word. */
function countStats(html: string | null) {
  const doc = new DOMParser().parseFromString(html ?? "", "text/html");
  return {
    h1: doc.querySelectorAll("h1").length,
    h2: doc.querySelectorAll("h2").length,
    h3: doc.querySelectorAll("h3").length,
    table: doc.querySelectorAll("table").length,
    para: doc.querySelectorAll("p").length,
  };
}

type EditMode = "md" | "word";

/**
 * Trang `/edit` (thay `/word`): soạn md (textarea + preview debounce 300ms) hoặc
 * word (upload .docx → mammoth) — 1 hàng DocStyleTools chung, css áp preview đang xem.
 * `?job=` (query param, job detail link sang trang này): md → GET job prefill textarea;
 * docx → downloadExport blob → mammoth prefill preview. Không có job → editor rỗng + upload.
 */
export default function Edit() {
  const [params] = useSearchParams();
  const jobId = params.get("job");

  const [mode, setMode] = useState<EditMode>("md");
  // Loading?job= fetch — derive từ id đã load (tránh setState đồng bộ trong effect).
  const [loadedJobId, setLoadedJobId] = useState<string | null>(null);
  const [md, setMd] = useState("");
  const [previewMd, setPreviewMd] = useState("");
  const [wordHtml, setWordHtml] = useState<string | null>(null);
  const [wordLoading, setWordLoading] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const [showStats, setShowStats] = useState(false);
  const [css, setCss] = useState(() => buildPreviewCss(DEFAULT_PREVIEW_OPTS));
  const mdRef = useRef<HTMLTextAreaElement>(null);

  // Prefill theo ?job= (1 lần cho mỗi job).
  useEffect(() => {
    if (jobId === null) return;
    let cancelled = false;
    (async () => {
      try {
        const job = await api.getJob(jobId);
        if (cancelled) return;
        if (job.output_format === "docx") {
          setMode("word");
          const blob = await api.downloadExport(jobId, "docx");
          const { value } = await mammoth.convertToHtml({ arrayBuffer: await blob.arrayBuffer() });
          if (!cancelled) setWordHtml(DOMPurify.sanitize(value));
        } else {
          setMd(job.result?.edited_markdown ?? job.result?.markdown ?? "");
        }
      } catch (err) {
        if (!cancelled) toast.error(mapApiError(err));
      } finally {
        if (!cancelled) setLoadedJobId(jobId);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  // Live preview: debounce 300ms sau mỗi lần đổi md.
  useEffect(() => {
    const t = setTimeout(() => setPreviewMd(md), 300);
    return () => clearTimeout(t);
  }, [md]);

  async function onFile(e: ChangeEvent<HTMLInputElement>) {
    const input = e.target;
    const file = input.files?.[0];
    if (!file) return;
    setFileError(null);
    setWordLoading(true);
    try {
      const { value } = await mammoth.convertToHtml({ arrayBuffer: await file.arrayBuffer() });
      // mammoth output untrusted → DOMPurify once before srcdoc (script stripped)
      setWordHtml(DOMPurify.sanitize(value));
    } catch {
      setFileError("Không đọc được file .docx này.");
    } finally {
      setWordLoading(false);
      input.value = "";
    }
  }

  /** Chèn `before`/`after` quanh selection của textarea md. */
  function applyAround(before: string, after = before) {
    const el = mdRef.current;
    if (!el) return;
    const s = el.selectionStart;
    const e = el.selectionEnd;
    const v = el.value;
    setMd(v.slice(0, s) + before + v.slice(s, e) + after + v.slice(e));
    const a = s + before.length;
    const b = e + before.length;
    window.setTimeout(() => {
      el.focus();
      el.setSelectionRange(a, b);
    }, 0);
  }

  /** Chèn prefix đầu dòng chứa selection (Heading 1/2). */
  function applyLinePrefix(prefix: string) {
    const el = mdRef.current;
    if (!el) return;
    const s = el.selectionStart;
    const v = el.value;
    const lineStart = v.lastIndexOf("\n", s - 1) + 1;
    setMd(v.slice(0, lineStart) + prefix + v.slice(lineStart));
    const a = s + prefix.length;
    window.setTimeout(() => {
      el.focus();
      el.setSelectionRange(a, a);
    }, 0);
  }

  // TOC source: HTML render của preview ĐANG xem (md → marked; word → mammoth).
  const mdHtml = useMemo(() => renderMarkdown(md), [md]);
  const previewDoc = useMemo(() => (wordHtml === null ? null : withStyle(wordHtml, css)), [wordHtml, css]);
  const activeHtml = mode === "md" ? mdHtml : wordHtml;
  const stats = useMemo(() => countStats(wordHtml), [wordHtml]);
  const statItems: Array<[string, number]> = [
    ["H1", stats.h1],
    ["H2", stats.h2],
    ["H3", stats.h3],
    ["Bảng", stats.table],
    ["Đoạn", stats.para],
  ];

  return (
    <main id="main" className="mx-auto max-w-6xl p-4 sm:p-6" data-testid="edit-page">
      <h1 className="mb-1 text-2xl font-bold tracking-tight">Soạn thảo</h1>
      <p className="mb-4 text-sm text-muted">
        Viết Markdown hoặc tải .docx — xem trước trình duyệt theo style đã chọn.
      </p>

      {/* Chế độ nội bộ: md / word (R51: không còn link nav cho trang này). */}
      <div className="mb-4 flex gap-2">
        <Button
          testid="edit-tab-md"
          variant="ghost"
          aria-pressed={mode === "md"}
          className={mode === "md" ? "bg-surface font-semibold" : ""}
          onClick={() => setMode("md")}
        >
          Markdown
        </Button>
        <Button
          testid="edit-tab-word"
          variant="ghost"
          aria-pressed={mode === "word"}
          className={mode === "word" ? "bg-surface font-semibold" : ""}
          onClick={() => setMode("word")}
        >
          Word
        </Button>
      </div>

      {jobId !== null && loadedJobId !== jobId && (
        <p data-testid="edit-loading" className="mb-4 text-sm text-muted">
          Đang tải công việc…
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-2 lg:items-start">
        {/* Pane word giữ testid root `word-tool` (R51: word-tool testids giữ — WordTool hấp thụ vào /edit). */}
        <div
          className="flex flex-col gap-4"
          data-testid={mode === "word" ? "word-tool" : undefined}
        >
          {mode === "md" ? (
            <Card testid="edit-md-card" title="Soạn Markdown">
              <div className="mb-2 flex gap-2">
                <Button
                  testid="edit-md-bold"
                  variant="secondary"
                  size="sm"
                  title="Đậm (quan quanh selection)"
                  onClick={() => applyAround("**")}
                >
                  B
                </Button>
                <Button
                  testid="edit-md-h1"
                  variant="secondary"
                  size="sm"
                  title="Heading 1"
                  onClick={() => applyLinePrefix("# ")}
                >
                  H1
                </Button>
                <Button
                  testid="edit-md-h2"
                  variant="secondary"
                  size="sm"
                  title="Heading 2"
                  onClick={() => applyLinePrefix("## ")}
                >
                  H2
                </Button>
              </div>
              <textarea
                ref={mdRef}
                data-testid="edit-md-input"
                value={md}
                onChange={(e) => setMd(e.target.value)}
                placeholder="Viết markdown ở đây…"
                className="h-64 w-full rounded-md border border-border bg-surface p-2 font-mono text-sm text-text"
              />
            </Card>
          ) : (
            <Card testid="word-upload" title="Tải file .docx">
              <label className="flex flex-col gap-1 text-sm">
                <span className="text-muted">Chọn file .docx</span>
                <input
                  type="file"
                  accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                  data-testid="input-word-file"
                  onChange={(e) => void onFile(e)}
                  className="block w-full cursor-pointer rounded-sm border border-border bg-surface px-3 py-2 text-sm text-text file:mr-3 file:cursor-pointer file:rounded-md file:border-0 file:bg-surface-2 file:px-3 file:py-1 file:text-text"
                />
              </label>
              {fileError && (
                <div
                  data-testid="word-file-error"
                  role="alert"
                  className="mt-2 rounded-md border border-error/40 bg-error/10 px-3 py-2 text-sm text-error"
                >
                  {fileError}
                </div>
              )}
            </Card>
          )}

          <Card
            testid={mode === "md" ? "edit-md-preview-card" : "word-preview-card"}
            title="Xem trước"
          >
            {mode === "md" ? (
              <MarkdownPreview markdown={previewMd} css={css} />
            ) : wordLoading ? (
              <p aria-busy="true" className="text-sm text-muted">
                Đang tải tài liệu…
              </p>
            ) : previewDoc === null ? (
              <div className="flex items-start gap-3">
                <FileText className="mt-0.5 h-5 w-5 shrink-0 text-muted" aria-hidden="true" />
                <div>
                  <p className="font-medium">{EMPTY_TITLE}</p>
                  <p className="text-sm text-muted">Chọn file .docx để xem trước nội dung.</p>
                </div>
              </div>
            ) : (
              <iframe
                data-testid="word-preview"
                sandbox=""
                title="Xem trước tài liệu Word"
                srcDoc={previewDoc}
                className="h-96 w-full rounded-md border border-border"
              />
            )}
          </Card>
        </div>

        <div className="flex flex-col gap-4">
          {/* 1 hàng tools duy nhất — css áp preview của pane đang xem (md/word). */}
          <Card testid="edit-tools" title="Công cụ định dạng">
            <DocStyleTools html={activeHtml} onChange={setCss} />

            {mode === "word" && (
              <div className="mt-3">
                <Button
                  testid="btn-word-stats"
                  variant="ghost"
                  aria-pressed={showStats}
                  title="Thống kê heading, bảng, đoạn"
                  disabled={wordHtml === null || wordLoading}
                  onClick={() => setShowStats((s) => !s)}
                >
                  <BarChart3 className="h-4 w-4" aria-hidden="true" />
                  Thống kê
                </Button>
                {showStats && wordHtml !== null && (
                  <div
                    data-testid="word-stats"
                    className="mt-3 grid grid-cols-2 gap-2 rounded-md border border-border bg-surface-2 p-3 text-sm sm:grid-cols-5"
                  >
                    {statItems.map(([label, count]) => (
                      <div key={label} className="flex items-center justify-between gap-2 sm:block">
                        <span className="text-muted">{label}</span>{" "}
                        <span className="font-mono font-semibold">{count}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </Card>
        </div>
      </div>
    </main>
  );
}
