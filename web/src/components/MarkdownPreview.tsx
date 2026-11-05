import DOMPurify from "dompurify";
import { marked } from "marked";

const DOC_PREFIX = "<!doctype html><meta charset=\"utf-8\">";

/* iframe sandbox="" không đọc được CSS của app → tự chứa style theo theme,
   nếu không bản xem trước sẽ trắng lóa trong dark mode. */
const DARK_CSS = `
  :root { color-scheme: dark; }
  body { margin:0; padding:4px 2px; background:#0f1115; color:#e6e8eb;
         font: 16px/1.75 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
  a { color:#7aa2f7; }
  h1,h2,h3 { line-height:1.3; margin:1.2em 0 .5em; }
  code, pre { background:#171a21; border-radius:6px; }
  pre { padding:12px 14px; overflow:auto; }
  table { border-collapse:collapse; } td,th { border:1px solid #2a2f3a; padding:6px 10px; }
  img { max-width:100%; height:auto; }
  blockquote { margin:1em 0; padding:.2em 0 .2em 14px; border-left:3px solid #2a2f3a; color:#a8b0bd; }
`;
const LIGHT_CSS = `
  :root { color-scheme: light; }
  body { margin:0; padding:4px 2px; background:#fff; color:#111418;
         font: 16px/1.75 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
  a { color:#1f5fd0; }
  h1,h2,h3 { line-height:1.3; margin:1.2em 0 .5em; }
  code, pre { background:#f3f4f6; border-radius:6px; }
  pre { padding:12px 14px; overflow:auto; }
  table { border-collapse:collapse; } td,th { border:1px solid #e3e6ea; padding:6px 10px; }
  img { max-width:100%; height:auto; }
  blockquote { margin:1em 0; padding:.2em 0 .2em 14px; border-left:3px solid #e3e6ea; color:#5b6472; }
`;

/**
 * Sandboxed, sanitized markdown preview (security-critical: VLM output untrusted).
 * iframe sandbox="" — no scripts, no same-origin; srcdoc pre-sanitized via DOMPurify.
 */
export default function MarkdownPreview({ markdown }: { markdown: string }) {
  // marked.parse returns string | Promise<string> when async extensions used; MVP assumes sync.
  const html = DOMPurify.sanitize(marked.parse(markdown) as string);
  const dark =
    typeof document === "undefined" ||
    document.documentElement.classList.contains("dark");
  const css = `<style>${dark ? DARK_CSS : LIGHT_CSS}</style>`;
  return (
    <iframe
      data-testid="preview-markdown"
      sandbox=""
      title="Xem trước Markdown"
      srcDoc={DOC_PREFIX + css + html}
    />
  );
}
