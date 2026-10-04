import DOMPurify from "dompurify";
import { marked } from "marked";

const DOC_PREFIX = "<!doctype html><meta charset=\"utf-8\">";

/**
 * Sandboxed, sanitized markdown preview (security-critical: VLM output untrusted).
 * iframe sandbox="" — no scripts, no same-origin; srcdoc pre-sanitized via DOMPurify.
 */
export default function MarkdownPreview({ markdown }: { markdown: string }) {
  // marked.parse returns string | Promise<string> when async extensions used; MVP assumes sync.
  const html = DOMPurify.sanitize(marked.parse(markdown) as string);
  return (
    <iframe
      data-testid="preview-markdown"
      sandbox=""
      title="Xem trước Markdown"
      srcDoc={DOC_PREFIX + html}
    />
  );
}
