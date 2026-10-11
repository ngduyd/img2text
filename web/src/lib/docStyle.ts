/** Style preview partag (DocStyleTools + UnifiedEditor): css builder + inject. */

import type { LayoutStyle } from "../api/types";

export const FONT_FAMILIES = ["system-ui", "Times New Roman", "Arial", "Georgia", "Courier New"];

export interface PreviewOpts {
  fontFamily: string;
  fontSize: number;
  index: boolean;
  marginLeft: number;
  marginRight: number;
  tableBorders: boolean;
}

/** Defaults dùng cho state của tools + css khởi tạo của preview (tránh flash chưa style). */
export const DEFAULT_PREVIEW_OPTS: PreviewOpts = {
  fontFamily: FONT_FAMILIES[0],
  fontSize: 16,
  index: false,
  marginLeft: 2.5,
  marginRight: 2.5,
  tableBorders: true,
};

/** 1 style block duy nhất cho srcdoc — đổi style chỉ đổi block này, không re-sanitize HTML gốc. */
export function buildPreviewCss(o: PreviewOpts): string {
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
    // var(--muted) safe: css chỉ scope trong app (.word-doc), token theo theme.
    rules.push("table, th, td { border: 1px solid var(--muted); border-collapse: collapse; }");
  }
  return rules.join("\n");
}

/**
 * Plan M4: word pane không còn iframe → wrap css sinh cho body (buildPreviewCss
 * + buildLayoutStyleCss) vào container `.word-doc`, `body` → `&` (CSS nesting)
 * để rule h1/table… scope dưới editor, không leak ra trang.
 */
export function scopeWordPaneCss(css: string): string {
  if (!css.trim()) return "";
  return `.word-doc { ${css.replace(/\bbody\b/g, "&")} }`;
}

/**
 * Plan M: job.layout_style (hoặc state tools word) → 1 body rule. Dùng cho
 * md preview (override client theo contract M1, scope `.md-pane .w-md-editor-preview`
 * trong UnifiedEditor) + wordCss của DocStyleTools (một builder duy nhất, khớp enum keys server).
 */
export function buildLayoutStyleCss(style: LayoutStyle | null | undefined): string {
  if (!style) return "";
  const rules: string[] = [];
  if (style.fontFamily !== undefined) rules.push(`font-family: ${JSON.stringify(style.fontFamily)}`);
  if (style.fontSize !== undefined) rules.push(`font-size: ${style.fontSize}px`);
  if (style.align !== undefined && style.align !== "left") rules.push(`text-align: ${style.align}`);
  if (style.indent !== undefined && style.indent > 0)
    rules.push(`padding-left: ${(style.indent * 1.5).toFixed(2)}rem`);
  if (style.spacing !== undefined && style.spacing !== "1.5") rules.push(`line-height: ${style.spacing}`);
  if (style.underline) rules.push("text-decoration: underline");
  return rules.length > 0 ? `body { ${rules.join("; ")}; }` : "";
}
