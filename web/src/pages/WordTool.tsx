import DOMPurify from "dompurify";
import { BarChart3, FileDown, FileOutput, FileText, Link } from "lucide-react";
import * as mammoth from "mammoth";
import { useMemo, useState, type ChangeEvent } from "react";
import Button from "../components/ui/Button";
import Card from "../components/ui/Card";
import Input from "../components/ui/Input";

/** Heading h1-h3 → #, p → text, ul/ol → list, table giữ nguyên HTML.
 * ponytail: đủ MVP — turndown lib nếu cần render HTML inline (strong/em/a) chính xác. */
function blockToMd(el: Element): string {
  const tag = el.tagName.toLowerCase();
  const heading = /^h([1-3])$/.exec(tag);
  if (heading) return `${"#".repeat(Number(heading[1]))} ${(el.textContent ?? "").trim()}`;
  if (tag === "p") return (el.textContent ?? "").trim();
  if (tag === "ul" || tag === "ol") {
    return Array.from(el.children)
      .map((li, i) => `${tag === "ol" ? `${i + 1}. ` : "- "}${(li.textContent ?? "").trim()}`)
      .join("\n");
  }
  if (tag === "table") return el.outerHTML;
  if (el.children.length > 0) {
    return Array.from(el.children).map(blockToMd).join("\n\n");
  }
  return (el.textContent ?? "").trim();
}

function htmlToMarkdown(html: string): string {
  const doc = new DOMParser().parseFromString(html, "text/html");
  return Array.from(doc.body.children)
    .map(blockToMd)
    .filter((line) => line.length > 0)
    .join("\n\n");
}

/** Stats từ HTML parse — count h1/h2/h3/table/đoạn (p). */
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

function downloadText(filename: string, text: string, mime: string) {
  const href = URL.createObjectURL(new Blob([text], { type: mime }));
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(href);
}

const EMPTY_TITLE = "Chưa có tài liệu";

/** D3 prototype `/word`: URL/upload .docx → mammoth preview + Markdown/stats tools. */
export default function WordTool() {
  const [url, setUrl] = useState("");
  const [html, setHtml] = useState<string | null>(null);
  const [urlError, setUrlError] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showStats, setShowStats] = useState(false);

  async function loadUrl() {
    const target = url.trim();
    if (!target) return;
    setUrlError(null);
    setFileError(null);
    setLoading(true);
    try {
      const res = await fetch(target);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const type = res.headers.get("content-type") ?? "";
      if (type.includes("officedocument") || type.includes("octet-stream")) {
        const { value } = await mammoth.convertToHtml({ arrayBuffer: await res.arrayBuffer() });
        setHtml(DOMPurify.sanitize(value));
      } else {
        setHtml(DOMPurify.sanitize(await res.text()));
      }
    } catch {
      // ponytail: CORS chặn fetch từ trình duyệt với URL ngoài — server-side fetch để sau (MVP: thử fetch thật, fail → hướng dẫn upload).
      setUrlError("Không tải được URL từ trình duyệt (CORS): dùng Tải file .docx");
    } finally {
      setLoading(false);
    }
  }

  async function onFile(e: ChangeEvent<HTMLInputElement>) {
    const input = e.target;
    const file = input.files?.[0];
    if (!file) return;
    setUrlError(null);
    setFileError(null);
    setLoading(true);
    try {
      const { value } = await mammoth.convertToHtml({ arrayBuffer: await file.arrayBuffer() });
      // mammoth output untrusted → DOMPurify before srcdoc (script stripped)
      setHtml(DOMPurify.sanitize(value));
    } catch {
      setFileError("Không đọc được file .docx này.");
    } finally {
      setLoading(false);
      input.value = "";
    }
  }

  const stats = useMemo(() => countStats(html), [html]);
  const statItems: Array<[string, number]> = [
    ["H1", stats.h1],
    ["H2", stats.h2],
    ["H3", stats.h3],
    ["Bảng", stats.table],
    ["Đoạn", stats.para],
  ];

  return (
    <main id="main" className="mx-auto max-w-3xl p-4 sm:p-6" data-testid="word-tool">
      <h1 className="mb-1 text-2xl font-bold tracking-tight">Công cụ Word</h1>
      <p className="mb-6 text-sm text-muted">
        Xem trước tài liệu Word trong trình duyệt, tải Markdown và thống kê heading.
      </p>

      {/* Card không nhận className (shared ui/Card) — spacing qua wrapper (Profile.tsx pattern). */}
      <div className="flex flex-col gap-4">
        <Card testid="word-url" title="Tải từ URL">
          <div className="flex flex-wrap items-end gap-2">
            <Input
              label="URL tài liệu"
              testid="input-word-url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://…/tai-lieu.docx"
              className="min-w-[min(320px,100%)] flex-1"
              onKeyDown={(e) => {
                if (e.key === "Enter" && !loading) void loadUrl();
              }}
            />
            <Button testid="btn-word-load" loading={loading} onClick={() => void loadUrl()}>
              <Link className="h-4 w-4" aria-hidden="true" />
              Tải URL
            </Button>
          </div>
          {urlError && (
            <div
              data-testid="word-url-error"
              role="alert"
              className="mt-2 rounded-md border border-error/40 bg-error/10 px-3 py-2 text-sm text-error"
            >
              {urlError}
            </div>
          )}
        </Card>

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

        <Card testid="word-preview-card" title="Xem trước">
          {loading ? (
            <p aria-busy="true" className="text-sm text-muted">
              Đang tải tài liệu…
            </p>
          ) : html === null ? (
            <div className="flex items-start gap-3">
              <FileText className="mt-0.5 h-5 w-5 shrink-0 text-muted" aria-hidden="true" />
              <div>
                <p className="font-medium">{EMPTY_TITLE}</p>
                <p className="text-sm text-muted">
                  Tải URL hoặc chọn file .docx để xem trước nội dung.
                </p>
              </div>
            </div>
          ) : (
            <iframe
              data-testid="word-preview"
              sandbox=""
              title="Xem trước tài liệu Word"
              srcDoc={html}
              className="h-96 w-full rounded-md border border-border"
            />
          )}
        </Card>

        <Card testid="word-tools" title="Công cụ">
          <div className="flex flex-wrap gap-2">
            <Button
              testid="btn-word-to-md"
              variant="secondary"
              title="Tải Markdown từ tài liệu hiện tại"
              disabled={html === null || loading}
              onClick={() => html !== null && downloadText("tai-lieu.md", htmlToMarkdown(html), "text/markdown;charset=utf-8")}
            >
              <FileDown className="h-4 w-4" aria-hidden="true" />
              Tải Markdown
            </Button>
            {/* Upgrade path: nối POST /api/jobs/{id}/export {fmt:"docx-layout"} (lane D2 server)
                khi trang này có job context — prototype độc lập nên luôn disabled. */}
            <Button
              testid="btn-word-export-docx"
              variant="secondary"
              disabled
              title="Xuất sau khi có job OCR"
            >
              <FileOutput className="h-4 w-4" aria-hidden="true" />
              Xuất DOCX (giữ layout)
            </Button>
            <Button
              testid="btn-word-stats"
              variant="ghost"
              aria-pressed={showStats}
              title="Thống kê heading, bảng, đoạn"
              disabled={html === null || loading}
              onClick={() => setShowStats((s) => !s)}
            >
              <BarChart3 className="h-4 w-4" aria-hidden="true" />
              Thống kê
            </Button>
          </div>
          {showStats && html !== null && (
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
        </Card>
      </div>
    </main>
  );
}
