import DOMPurify from "dompurify";
import { BarChart3, FileText } from "lucide-react";
import * as mammoth from "mammoth";
import { useMemo, useState, type ChangeEvent } from "react";
import Button from "../components/ui/Button";
import Card from "../components/ui/Card";
import Input from "../components/ui/Input";

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

/** Danh sách text heading h1-h3 — nguồn hiển thị mục lục (word-toc). */
function extractToc(html: string | null): string[] {
  const doc = new DOMParser().parseFromString(html ?? "", "text/html");
  return Array.from(doc.querySelectorAll("h1, h2, h3"))
    .map((h) => (h.textContent ?? "").trim())
    .filter((t) => t.length > 0);
}

const FONT_FAMILIES = ["system-ui", "Times New Roman", "Arial", "Georgia", "Courier New"];
const EMPTY_TITLE = "Chưa có tài liệu";

interface PreviewOpts {
  fontFamily: string;
  fontSize: number;
  index: boolean;
  marginLeft: number;
  marginRight: number;
  tableBorders: boolean;
}

/** 1 style block duy nhất cho srcdoc — đổi style chỉ đổi block này, không re-sanitize HTML gốc. */
function buildPreviewCss(o: PreviewOpts): string {
  const rules = [
    `body { font-family: ${JSON.stringify(o.fontFamily)}; font-size: ${o.fontSize}px; padding-left: ${o.marginLeft}cm; padding-right: ${o.marginRight}cm; }`,
  ];
  if (o.index) {
    rules.push(
      "body { counter-reset: h1c h2c h3c; }",
      "h1 { counter-increment: h1c; counter-reset: h2c h3c; }",
      'h1::before { content: counter(h1c) ". "; }',
      "h2 { counter-increment: h2c; counter-reset: h3c; }",
      'h2::before { content: counter(h1c) "." counter(h2c) " "; }',
      "h3 { counter-increment: h3c; }",
      'h3::before { content: counter(h1c) "." counter(h2c) "." counter(h3c) " "; }',
    );
  }
  if (o.tableBorders) {
    rules.push("table, th, td { border: 1px solid #8b949e; border-collapse: collapse; }");
  }
  return rules.join("\n");
}

/** Chèn style tag (id word-style) vào HTML đã sanitize — không đụng nội dung gốc. */
function withStyle(html: string, css: string): string {
  const tag = `<style id="word-style">${css}</style>`;
  if (/<head[^>]*>/i.test(html)) return html.replace(/<head[^>]*>/i, (m) => `${m}${tag}`);
  return tag + html;
}

const SELECT_CLS =
  "h-10 rounded-sm border border-border bg-surface px-2 text-text file:cursor-pointer";

/** D3 prototype `/word`: upload .docx → mammoth preview + tools định dạng (chữ/index/lề/bảng). */
export default function WordTool() {
  const [html, setHtml] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showStats, setShowStats] = useState(false);

  // Format tools state
  const [fontFamily, setFontFamily] = useState(FONT_FAMILIES[0]);
  const [fontSize, setFontSize] = useState(16);
  const [indexOn, setIndexOn] = useState(false);
  const [marginLeft, setMarginLeft] = useState(2.5);
  const [marginRight, setMarginRight] = useState(2.5);
  const [tableBorders, setTableBorders] = useState(true);

  async function onFile(e: ChangeEvent<HTMLInputElement>) {
    const input = e.target;
    const file = input.files?.[0];
    if (!file) return;
    setFileError(null);
    setLoading(true);
    try {
      const { value } = await mammoth.convertToHtml({ arrayBuffer: await file.arrayBuffer() });
      // mammoth output untrusted → DOMPurify once before srcdoc (script stripped)
      setHtml(DOMPurify.sanitize(value));
    } catch {
      setFileError("Không đọc được file .docx này.");
    } finally {
      setLoading(false);
      input.value = "";
    }
  }

  const css = useMemo(
    () => buildPreviewCss({ fontFamily, fontSize, index: indexOn, marginLeft, marginRight, tableBorders }),
    [fontFamily, fontSize, indexOn, marginLeft, marginRight, tableBorders],
  );
  const previewDoc = useMemo(() => (html === null ? null : withStyle(html, css)), [html, css]);
  const stats = useMemo(() => countStats(html), [html]);
  const toc = useMemo(() => extractToc(html), [html]);
  const statItems: Array<[string, number]> = [
    ["H1", stats.h1],
    ["H2", stats.h2],
    ["H3", stats.h3],
    ["Bảng", stats.table],
    ["Đoạn", stats.para],
  ];

  function clamp(v: string, min: number, max: number, fallback: number): number {
    const n = Number(v);
    return Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : fallback;
  }

  return (
    <main id="main" className="mx-auto max-w-6xl p-4 sm:p-6" data-testid="word-tool">
      <h1 className="mb-1 text-2xl font-bold tracking-tight">Công cụ Word</h1>
      <p className="mb-6 text-sm text-muted">
        Định dạng văn bản: chữ, mục lục, lề, bảng — xem trước trình duyệt theo style đã chọn.
      </p>

      {/* Card không nhận className (shared ui/Card) — spacing qua wrapper (Profile.tsx pattern). */}
      <div className="flex flex-col gap-4">
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

        <div className="grid gap-4 lg:grid-cols-2 lg:items-start">
          <Card testid="word-preview-card" title="Xem trước">
            {loading ? (
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

          <Card testid="word-tools" title="Công cụ định dạng">
            {/* Chữ (Font) */}
            <div className="mb-3">
              <label className="flex flex-col gap-1 text-sm" htmlFor="tool-font-family">
                <span className="text-muted">Font chữ</span>
                <select
                  id="tool-font-family"
                  data-testid="tool-font-family"
                  value={fontFamily}
                  onChange={(e) => setFontFamily(e.target.value)}
                  className={SELECT_CLS}
                >
                  {FONT_FAMILIES.map((f) => (
                    <option key={f} value={f}>
                      {f}
                    </option>
                  ))}
                </select>
              </label>
              <div className="mt-2">
                <Input
                  label="Cỡ chữ (px, 8–72)"
                  testid="tool-font-size"
                  type="number"
                  min={8}
                  max={72}
                  value={fontSize}
                  onChange={(e) => setFontSize(clamp(e.target.value, 8, 72, fontSize))}
                />
              </div>
            </div>

            {/* Index (Mục lục) */}
            <div className="mb-3">
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  data-testid="tool-index-toggle"
                  checked={indexOn}
                  onChange={(e) => setIndexOn(e.target.checked)}
                  className="h-4 w-4 accent-accent"
                />
                Đánh số heading + sinh mục lục
              </label>
              {indexOn && (
                <div
                  data-testid="word-toc"
                  className="mt-2 max-h-40 overflow-auto rounded-md border border-border bg-surface-2 p-3 text-sm"
                >
                  <p className="mb-1 font-medium">Mục lục</p>
                  {toc.length === 0 ? (
                    <p className="text-muted">Không có heading h1–h3.</p>
                  ) : (
                    <ol className="list-decimal space-y-1 pl-4">
                      {toc.map((t, i) => (
                        <li key={`${i}-${t}`}>{t}</li>
                      ))}
                    </ol>
                  )}
                </div>
              )}
            </div>

            {/* Lề (Margin) */}
            <div className="mb-3 grid grid-cols-2 gap-2">
              <Input
                label="Lề trái (cm)"
                testid="tool-margin-left"
                type="number"
                min={0}
                max={8}
                step={0.5}
                value={marginLeft}
                onChange={(e) => setMarginLeft(clamp(e.target.value, 0, 8, marginLeft))}
              />
              <Input
                label="Lề phải (cm)"
                testid="tool-margin-right"
                type="number"
                min={0}
                max={8}
                step={0.5}
                value={marginRight}
                onChange={(e) => setMarginRight(clamp(e.target.value, 0, 8, marginRight))}
              />
            </div>

            {/* Bảng (Table) */}
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                data-testid="tool-table-borders"
                checked={tableBorders}
                onChange={(e) => setTableBorders(e.target.checked)}
                className="h-4 w-4 accent-accent"
              />
              Viền bảng
            </label>

            <div className="mt-3">
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
            </div>
          </Card>
        </div>
      </div>
    </main>
  );
}
