import { useEffect, useMemo, useState } from "react";
import Input from "./ui/Input";

const FONT_FAMILIES = ["system-ui", "Times New Roman", "Arial", "Georgia", "Courier New"];
const SELECT_CLS =
  "h-10 rounded-sm border border-border bg-surface px-2 text-text file:cursor-pointer";

interface StyleOpts {
  fontFamily: string;
  fontSize: number;
  index: boolean;
  marginLeft: number;
  marginRight: number;
  tableBorders: boolean;
}

/** CSS cho preview iframe — copy WordTool.buildPreviewCss (font/index/lề/bảng). */
function buildStyleCss(o: StyleOpts): string {
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

function clamp(v: string, min: number, max: number, fallback: number): number {
  const n = Number(v);
  return Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : fallback;
}

/**
 * Doc style tools — 4 nhóm (chữ / mục lục / lề / bảng), pattern copy từ /word
 * (WordTool). Builds CSS and reports it via onChange; PreviewTabs injects the
 * CSS into the preview iframes (md + docx).
 */
export default function DocStyleTools({ onChange }: { onChange: (css: string) => void }) {
  const [fontFamily, setFontFamily] = useState(FONT_FAMILIES[0]);
  const [fontSize, setFontSize] = useState(16);
  const [indexOn, setIndexOn] = useState(false);
  const [marginLeft, setMarginLeft] = useState(2.5);
  const [marginRight, setMarginRight] = useState(2.5);
  const [tableBorders, setTableBorders] = useState(true);

  const css = useMemo(
    () =>
      buildStyleCss({ fontFamily, fontSize, index: indexOn, marginLeft, marginRight, tableBorders }),
    [fontFamily, fontSize, indexOn, marginLeft, marginRight, tableBorders],
  );
  useEffect(() => {
    onChange(css);
  }, [css, onChange]);

  return (
    <section
      data-testid="doc-style-tools"
      aria-label="Công cụ định dạng"
      className="mt-4 border-t border-border pt-3"
    >
      <p className="mb-2 text-sm font-semibold">Công cụ định dạng</p>
      <div className="grid gap-3 sm:grid-cols-2">
        {/* Chữ (Font) */}
        <div className="flex flex-col gap-2">
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

        {/* Lề (Margin) */}
        <div className="grid grid-cols-2 gap-2">
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

        {/* Index (Mục lục) */}
        <label className="flex items-center gap-2 self-start text-sm">
          <input
            type="checkbox"
            data-testid="tool-index-toggle"
            checked={indexOn}
            onChange={(e) => setIndexOn(e.target.checked)}
            className="h-4 w-4 accent-accent"
          />
          Đánh số heading
        </label>

        {/* Bảng (Table) */}
        <label className="flex items-center gap-2 self-start text-sm">
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
    </section>
  );
}
