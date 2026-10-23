import { useEffect, useMemo, useState } from "react";
import { IndentDecrease, IndentIncrease } from "lucide-react";
import type { LayoutStyle } from "../api/types";
import { DEFAULT_PREVIEW_OPTS, buildLayoutStyleCss, buildPreviewCss } from "../lib/docStyle";
import { useT } from "../i18n";
import Button from "./ui/Button";
import Input from "./ui/Input";

type Align = "left" | "center" | "justify";

const LINE_SPACINGS = ["1", "1.25", "1.5"];

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
 * Bộ tool định dạng pane WORD (/edit mode word, M4): chỉ controls TRANG-LEVEL —
 * margin, giãn dòng, TOC/đánh số heading, viền bảng, indent trang.
 * R51 exception (lệnh user): gỡ control NỘI DUNG trùng toolbar Tiptap M4
 * (tool-font-family, tool-font-size, word-style-align-*, word-style-underline) —
 * toolbar xử lý theo vùng chọn.
 * css bắn qua onChange (baseCss) + onWordChange (wordCss); state style nằm đây.
 * `html` (optional) = HTML render của preview — nguồn sinh TOC (word-toc).
 * Plan M3: hydrate từ job.layout_style + emit bản PUT layout-style (onStyleChange);
 * fontFamily/fontSize/align/underline GIỮ state (key LayoutStyle server, export
 * fallback dùng) nhưng KHÔNG còn UI control.
 */
export default function DocStyleTools({
  html = null,
  onChange,
  onWordChange,
  initialStyle = null,
  onStyleChange,
}: {
  html?: string | null;
  onChange: (css: string) => void;
  onWordChange?: (css: string) => void;
  /** Plan M: hydrate từ job.layout_style (lưu ở session trước) + emit bản PUT layout-style. */
  initialStyle?: LayoutStyle | null;
  onStyleChange?: (style: LayoutStyle) => void;
}) {
  const { t } = useT();
  // Font/align/underline: state hydrate từ layout_style, không UI control (gỡ theo
  // lệnh user — trùng toolbar Tiptap) nhưng vẫn phát trong wordStyle → PUT giữ key.
  const [fontFamily] = useState(initialStyle?.fontFamily ?? DEFAULT_PREVIEW_OPTS.fontFamily);
  const [fontSize] = useState(initialStyle?.fontSize ?? DEFAULT_PREVIEW_OPTS.fontSize);
  const [indexOn, setIndexOn] = useState(DEFAULT_PREVIEW_OPTS.index);
  const [marginLeft, setMarginLeft] = useState(DEFAULT_PREVIEW_OPTS.marginLeft);
  const [marginRight, setMarginRight] = useState(DEFAULT_PREVIEW_OPTS.marginRight);
  const [tableBorders, setTableBorders] = useState(DEFAULT_PREVIEW_OPTS.tableBorders);
  // Page layout: indent/line spacing có UI; align/underline chỉ hydrate (xem trên).
  const [align] = useState<Align>(initialStyle?.align ?? "left");
  const [indent, setIndent] = useState(initialStyle?.indent ?? 0);
  const [spacing, setSpacing] = useState(initialStyle?.spacing ?? "1.5");
  const [underline] = useState(initialStyle?.underline ?? false);

  const css = useMemo(
    () => buildPreviewCss({ fontFamily, fontSize, index: indexOn, marginLeft, marginRight, tableBorders }),
    [fontFamily, fontSize, indexOn, marginLeft, marginRight, tableBorders],
  );
  useEffect(() => {
    onChange(css);
  }, [css, onChange]);

  // 1 builder cho word css + bản lưu PUT layout-style (enum keys khớp server).
  const wordStyle = useMemo<LayoutStyle>(
    () => ({ fontFamily, fontSize, align, indent, spacing, underline }),
    [fontFamily, fontSize, align, indent, spacing, underline],
  );
  const wordCss = useMemo(() => buildLayoutStyleCss(wordStyle), [wordStyle]);
  useEffect(() => {
    onWordChange?.(wordCss);
  }, [wordCss, onWordChange]);
  useEffect(() => {
    onStyleChange?.(wordStyle);
  }, [wordStyle, onStyleChange]);

  const toc = useMemo(() => extractToc(html), [html]);

  function clamp(v: string, min: number, max: number, fallback: number): number {
    const n = Number(v);
    return Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : fallback;
  }

  return (
    <div data-testid="doc-style-tools">
      {/* Index (Mục lục) */}
      <div className="mb-3">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            data-testid="tool-index-toggle"
            checked={indexOn}
            onChange={(e) => setIndexOn(e.target.checked)}
            className="h-6 w-6 accent-accent"
          />
          {t("docStyle.indexHeading")}
        </label>
        {indexOn && (
          <div
            data-testid="word-toc"
            className="mt-2 max-h-40 overflow-auto rounded-md border border-border bg-surface-2 p-3 text-sm"
          >
            <p className="mb-1 font-medium">{t("docStyle.tocTitle")}</p>
            {toc.length === 0 ? (
              <p className="text-muted">{t("docStyle.tocEmpty")}</p>
            ) : (
              <ol className="list-decimal space-y-1 pl-4">
                {toc.map((heading, i) => (
                  <li key={`${i}-${heading}`}>{heading}</li>
                ))}
              </ol>
            )}
          </div>
        )}
      </div>

      {/* Lề (Margin) */}
      <div className="mb-3 grid grid-cols-2 gap-2">
        <Input
          label={t("docStyle.marginLeft")}
          testid="tool-margin-left"
          type="number"
          min={0}
          max={8}
          step={0.5}
          value={marginLeft}
          onChange={(e) => setMarginLeft(clamp(e.target.value, 0, 8, marginLeft))}
        />
        <Input
          label={t("docStyle.marginRight")}
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
          className="h-6 w-6 accent-accent"
        />
        {t("docStyle.tableBorders")}
      </label>

      {/* Bố cục trang word: indent/giãn dòng */}
      <div data-testid="word-tools" className="mt-3 border-t border-border pt-3">
        <div className="mb-3 flex items-center gap-2">
          <Button
            testid="word-style-indent-out"
            variant="ghost"
            size="sm"
            title={t("docStyle.indentOut")}
            aria-label={t("docStyle.indentOut")}
            disabled={indent === 0}
            onClick={() => setIndent((n) => Math.max(0, n - 1))}
          >
            <IndentDecrease className="h-4 w-4" aria-hidden="true" />
          </Button>
          <Button
            testid="word-style-indent-in"
            variant="ghost"
            size="sm"
            title={t("docStyle.indentIn")}
            aria-label={t("docStyle.indentIn")}
            onClick={() => setIndent((n) => Math.min(4, n + 1))}
          >
            <IndentIncrease className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>
        <label className="flex items-center gap-2 text-sm" htmlFor="tool-line-spacing">
          <span className="text-muted">{t("docStyle.lineSpacing")}</span>
          <select
            id="tool-line-spacing"
            data-testid="word-style-spacing"
            value={spacing}
            onChange={(e) => setSpacing(e.target.value)}
            className={SELECT_CLS}
          >
            {LINE_SPACINGS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
      </div>
    </div>
  );
}
