import { useEffect, useMemo, useState } from "react";
import { AlignCenter, AlignJustify, AlignLeft, IndentDecrease, IndentIncrease } from "lucide-react";
import { DEFAULT_PREVIEW_OPTS, FONT_FAMILIES, buildPreviewCss } from "../lib/docStyle";
import Button from "./ui/Button";
import Input from "./ui/Input";

type DocStyleVariant = "md" | "word";

type Align = "left" | "center" | "justify";

const ALIGNS: { value: Align; testid: string; title: string; Icon: typeof AlignLeft }[] = [
  { value: "left", testid: "word-tb-align-left", title: "Căn trái", Icon: AlignLeft },
  { value: "center", testid: "word-tb-align-center", title: "Căn giữa", Icon: AlignCenter },
  { value: "justify", testid: "word-tb-align-justify", title: "Căn đều", Icon: AlignJustify },
];

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
 * Bộ tool định dạng doc partag (pane md/word của /edit): state style nằm đây,
 * css mới bắn ra qua onChange (nhận setter useState ổn định). `html` (optional)
 * = HTML render của preview đang xem — nguồn sinh TOC (word-toc, R51 giữ testid).
 * JD2: variant="word" (pane DOCX) THÊM controls bố cục trang — css qua
 * onWordChange, chỉ áp trong word pane (PreviewTabs inject riêng cho docx).
 */
export default function DocStyleTools({
  html = null,
  onChange,
  variant = "md",
  onWordChange,
}: {
  html?: string | null;
  onChange: (css: string) => void;
  variant?: DocStyleVariant;
  onWordChange?: (css: string) => void;
}) {
  const [fontFamily, setFontFamily] = useState(DEFAULT_PREVIEW_OPTS.fontFamily);
  const [fontSize, setFontSize] = useState(DEFAULT_PREVIEW_OPTS.fontSize);
  const [indexOn, setIndexOn] = useState(DEFAULT_PREVIEW_OPTS.index);
  const [marginLeft, setMarginLeft] = useState(DEFAULT_PREVIEW_OPTS.marginLeft);
  const [marginRight, setMarginRight] = useState(DEFAULT_PREVIEW_OPTS.marginRight);
  const [tableBorders, setTableBorders] = useState(DEFAULT_PREVIEW_OPTS.tableBorders);
  // Word-only page layout: align/indent/line spacing/underline → CSS cho docx pane.
  const [align, setAlign] = useState<Align>("left");
  const [indent, setIndent] = useState(0);
  const [spacing, setSpacing] = useState("1.5");
  const [underline, setUnderline] = useState(false);

  const css = useMemo(
    () => buildPreviewCss({ fontFamily, fontSize, index: indexOn, marginLeft, marginRight, tableBorders }),
    [fontFamily, fontSize, indexOn, marginLeft, marginRight, tableBorders],
  );
  useEffect(() => {
    onChange(css);
  }, [css, onChange]);

  const wordCss = useMemo(() => {
    if (variant !== "word") return "";
    const rules: string[] = [];
    if (align !== "left") rules.push(`text-align: ${align}`);
    if (indent > 0) rules.push(`padding-left: ${(indent * 1.5).toFixed(2)}rem`);
    if (spacing !== "1.5") rules.push(`line-height: ${spacing}`);
    if (underline) rules.push("text-decoration: underline");
    return rules.length > 0 ? `body { ${rules.join("; ")}; }` : "";
  }, [variant, align, indent, spacing, underline]);
  useEffect(() => {
    onWordChange?.(wordCss);
  }, [wordCss, onWordChange]);

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
            label="Cỡ chữ (px, 8-72)"
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
              <p className="text-muted">Không có heading h1-h3.</p>
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

      {/* JD2 word pane: bố cục trang (align/indent/giãn dòng/gạch chân) */}
      {variant === "word" && (
        <div data-testid="word-tools" className="mt-3 border-t border-border pt-3">
          <div className="mb-3 flex items-center gap-2">
            {ALIGNS.map(({ value, testid, title, Icon }) => (
              <Button
                key={value}
                testid={testid}
                variant="ghost"
                size="sm"
                title={title}
                aria-label={title}
                aria-pressed={align === value}
                className={align === value ? "bg-surface-2" : ""}
                onClick={() => setAlign(value)}
              >
                <Icon className="h-4 w-4" aria-hidden="true" />
              </Button>
            ))}
            <span className="mx-1 h-5 w-px bg-border" aria-hidden="true" />
            <Button
              testid="word-tb-indent-out"
              variant="ghost"
              size="sm"
              title="Bớt lề"
              aria-label="Bớt lề"
              disabled={indent === 0}
              onClick={() => setIndent((n) => Math.max(0, n - 1))}
            >
              <IndentDecrease className="h-4 w-4" aria-hidden="true" />
            </Button>
            <Button
              testid="word-tb-indent-in"
              variant="ghost"
              size="sm"
              title="Thêm lề"
              aria-label="Thêm lề"
              onClick={() => setIndent((n) => Math.min(4, n + 1))}
            >
              <IndentIncrease className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
          <div className="flex flex-wrap items-center gap-4">
            <label className="flex items-center gap-2 text-sm" htmlFor="tool-line-spacing">
              <span className="text-muted">Giãn dòng</span>
              <select
                id="tool-line-spacing"
                data-testid="word-tb-spacing"
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
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                data-testid="word-tb-underline"
                checked={underline}
                onChange={(e) => setUnderline(e.target.checked)}
                className="h-4 w-4 accent-accent"
              />
              Gạch chân chữ
            </label>
          </div>
        </div>
      )}
    </div>
  );
}
