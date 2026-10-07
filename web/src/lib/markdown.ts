import DOMPurify from "dompurify";
import { marked } from "marked";

/** marked + DOMPurify — nguồn render cho preview iframe và TOC của DocStyleTools. */
export function renderMarkdown(markdown: string): string {
  return DOMPurify.sanitize(markdown ? (marked.parse(markdown) as string) : "");
}
