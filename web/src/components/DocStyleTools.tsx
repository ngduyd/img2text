import { useEffect, useMemo, useState } from "react";
import { DEFAULT_PREVIEW_OPTS, FONT_FAMILIES, buildPreviewCss } from "../lib/docStyle";
import Input from "./ui/Input";

/** Danh sách text heading h1-h3 — nguồn hiển thị mục lục (word-toc). */
function extractToc(html: string | null): string[] {
  const doc = new DOMParser().parseFromString(html ?? "", "text/html");
  return Array.from(doc.querySelectorAll("h1, h2, h3"))
    .map((h) => (h.textContent ?? "").trim())
    .filter((t) => t.length > 0);
}

const SELECT_CLS =
  "h-10 rounded-sm border border-border bg-surface px-2 text-text file:cursor-pointer";

/**
 * Bộ tool định dạng doc partag (pane md/word của /edit): state style nằm đây,
 * css mới bắn ra qua onChange (nhận setter useState ổn định). `html` (optional)
 * = HTML render của preview đang xem — nguồn sinh TOC (word-toc, R51 giữ testid).
 */
export default function DocStyleTools({
  html = null,
  onChange,
}: {
  html?: string | null;
  onChange: (css: string) => void;
}) {
  const [fontFamily, setFontFamily] = useState(DEFAULT_PREVIEW_OPTS.fontFamily);
  const [fontSize, setFontSize] = useState(DEFAULT_PREVIEW_OPTS.fontSize);
  const [indexOn, setIndexOn] = useState(DEFAULT_PREVIEW_OPTS.index);
  const [marginLeft, setMarginLeft] = useState(DEFAULT_PREVIEW_OPTS.marginLeft);
  const [marginRight, setMarginRight] = useState(DEFAULT_PREVIEW_OPTS.marginRight);
  const [tableBorders, setTableBorders] = useState(DEFAULT_PREVIEW_OPTS.tableBorders);

  const css = useMemo(
    () => buildPreviewCss({ fontFamily, fontSize, index: indexOn, marginLeft, marginRight, tableBorders }),
    [fontFamily, fontSize, indexOn, marginLeft, marginRight, tableBorders],
  );
  useEffect(() => {
    onChange(css);
  }, [css, onChange]);
  const toc = useMemo(() => extractToc(html), [html]);

  function clamp(v: string, min: number, max: number, fallback: number): number {
    const n = Number(v);
    return Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : fallback;
  }

  return (
    <div data-testid="doc-style-tools">
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
    </div>
  );
}
