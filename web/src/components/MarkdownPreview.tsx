import { withStyle } from "../lib/docStyle";
import { renderMarkdown } from "../lib/markdown";

const DOC_PREFIX = "<!doctype html><meta charset=\"utf-8\">";

/**
 * Sandboxed, sanitized markdown preview (security-critical: VLM output untrusted).
 * iframe sandbox="" — no scripts, no same-origin; srcdoc pre-sanitized via DOMPurify.
 * `css` (optional) = style block của DocStyleTools chèn SAU sanitize (trusted builder CSS).
 */
export default function MarkdownPreview({
  markdown,
  css,
  className = "",
}: {
  markdown: string;
  css?: string;
  className?: string;
}) {
  const html = renderMarkdown(markdown);
  return (
    <iframe
      data-testid="preview-markdown"
      sandbox=""
      title="Xem trước Markdown"
      srcDoc={DOC_PREFIX + (css ? withStyle(html, css) : html)}
      className={className}
    />
  );
}
