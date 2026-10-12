import { useEffect, useMemo, useState } from "react";
import DOMPurify from "dompurify";
import MarkdownIt from "markdown-it";
import * as mammoth from "mammoth";
import { api } from "../api/client";
import type { Job } from "../api/types";
import { buildLayoutStyleCss, buildPreviewDocCss } from "../lib/docStyle";
import { mapApiError } from "../lib/errors";
import Button from "./ui/Button";
import Skeleton from "./ui/Skeleton";

type Mode = "md" | "word";

const FMT: Record<Mode, "md-layout" | "docx-layout"> = {
  md: "md-layout",
  word: "docx-layout",
};

/**
 * WS-UI Section "Layout": XEM TRƯỚC read-only mặc định (spec 2026-10-13).
 * - word: iframe sandbox srcDoc = docx.html + <style>{docStyle}</style>
 * - md: md → HTML (markdown-it) + docStyle scope .layout-preview → DOMPurify
 * Toggle "Chỉnh sửa" do JobDetail nắm (state editing) — component này chỉ preview.
 */
export default function LayoutPreview({ job }: { job: Job }) {
  const [mode, setMode] = useState<Mode>(job.output_format === "docx" ? "word" : "md");
  const [mdHtml, setMdHtml] = useState<string | null>(null);
  const [wordHtml, setWordHtml] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const docStyle = useMemo(() => buildLayoutStyleCss(job.layout_style), [job.layout_style]);
  /** Base doc style (spec #3): md pane scope .layout-preview; word iframe scope body. */
  const mdBase = useMemo(() => buildPreviewDocCss(".layout-preview"), []);
  const wordBase = useMemo(() => buildPreviewDocCss("body"), []);
  /** md pane: scope rule `body {…}` xuống container (contract M1 — không leak trang). */
  const mdStyle = useMemo(
    () => (docStyle ? docStyle.replace(/^body\b/, ".layout-preview") : ""),
    [docStyle],
  );

  const load = async (m: Mode) => {
    setLoading(true);
    setError(null);
    try {
      if (m === "md") {
        if (mdHtml === null) {
          await api.exportJob(job.id, FMT.md);
          const blob = await api.downloadExport(job.id, FMT.md);
          const md = new MarkdownIt({ html: false, linkify: true });
          // markdown-it (html:false escape HTML thô) + DOMPurify — 2 tầng.
          setMdHtml(DOMPurify.sanitize(md.render(await blob.text())));
        }
      } else if (wordHtml === null) {
        const cached = job.layout_cache?.docx_html
          ? await api.getDocxHtml(job.id)
          : null;
        if (cached !== null) {
          setWordHtml(DOMPurify.sanitize(cached));
        } else {
          await api.exportJob(job.id, FMT.word);
          const blob = await api.downloadExport(job.id, FMT.word);
          const { value } = await mammoth.convertToHtml({
            arrayBuffer: await blob.arrayBuffer(),
          });
          setWordHtml(DOMPurify.sanitize(value));
        }
      }
    } catch (err) {
      setError(mapApiError(err));
    } finally {
      setLoading(false);
    }
  };

  // Chỉ fetch mode đầu tiên; đổi mode → fetch cache state (mdHtml/wordHtml null check).
  // oxlint-disable-next-line react/set-state-in-effect
  useEffect(() => {
    void load(mode);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load theo mode, state check trong load
  }, [mode]);

  return (
    <section data-testid="layout-preview" className="flex min-w-0 flex-col gap-3">
      <div
        role="group"
        aria-label="Chế độ xem trước"
        className="inline-flex w-fit items-center gap-1 rounded-md border border-border p-1"
      >
        <Button
          testid="preview-mode-md"
          variant="ghost"
          size="sm"
          aria-pressed={mode === "md"}
          className={mode === "md" ? "bg-surface-2 font-semibold" : ""}
          onClick={() => setMode("md")}
        >
          Markdown
        </Button>
        <Button
          testid="preview-mode-word"
          variant="ghost"
          size="sm"
          aria-pressed={mode === "word"}
          className={mode === "word" ? "bg-surface-2 font-semibold" : ""}
          onClick={() => setMode("word")}
        >
          Word
        </Button>
      </div>
      {error !== null && (
        <div
          data-testid="preview-error"
          role="alert"
          className="flex flex-wrap items-center gap-3 rounded-md border border-error/40 bg-error/10 px-3 py-2 text-sm text-error"
        >
          <span className="min-w-0 flex-1 break-words">{error}</span>
          <Button
            testid="btn-retry-preview"
            variant="secondary"
            size="sm"
            onClick={() => void load(mode)}
          >
            Thử lại
          </Button>
        </div>
      )}
      {loading ? (
        <div data-testid="preview-loading" role="status" className="flex flex-col gap-2">
          <Skeleton className="h-4 w-1/3" />
          <Skeleton className="h-96 w-full" />
        </div>
      ) : mode === "md" ? (
        <div
          data-testid="preview-md"
          className="layout-preview max-h-[75vh] overflow-auto rounded-md border border-border p-4 leading-[1.7] text-text"
        >
          <style>{mdBase + mdStyle}</style>
          {mdHtml !== null && <div dangerouslySetInnerHTML={{ __html: mdHtml }} />}
        </div>
      ) : (
        <iframe
          data-testid="preview-word"
          title="Xem trước layout Word"
          sandbox=""
          // docStyle (body rule) + docx.html — srcdoc cùng origin iframe, sandbox off script.
          srcDoc={`<style>${wordBase}${docStyle}</style>${wordHtml ?? ""}`}
          className="h-[75vh] w-full rounded-md border border-border bg-surface"
        />
      )}
    </section>
  );
}
