import { useEffect, useMemo, useState } from "react";
import DOMPurify from "dompurify";
import MarkdownIt from "markdown-it";
import * as mammoth from "mammoth";
import { api } from "../api/client";
import type { Job } from "../api/types";
import { buildLayoutStyleCss, buildPreviewDocCss } from "../lib/docStyle";
import { mapApiError } from "../lib/errors";
import { useT } from "../i18n";
import Button from "./ui/Button";
import Skeleton from "./ui/Skeleton";

type Mode = "md" | "word";

const FMT: Record<Mode, "md-layout" | "docx-layout"> = {
  md: "md-layout",
  word: "docx-layout",
};

/** md → sanitize: markdown-it html:false + DOMPurify (2 tầng). */
function renderMdHtml(mdText: string): string {
  const md = new MarkdownIt({ html: false, linkify: true });
  return DOMPurify.sanitize(md.render(mdText));
}

/**
 * WS-UI Section "Layout": XEM TRƯỚC read-only (spec 2026-10-13).
 * - word: iframe sandbox srcDoc = docx.html + <style>{docStyle}</style>
 * - md: md → HTML (markdown-it) + docStyle scope .layout-preview → DOMPurify
 * Lane I Task 4: bỏ editing/textarea wave-3 G — sửa tay qua UnifiedEditor (btn-edit-doc).
 * U7: bỏ preview toggle — mode CONTROLLED bởi fmt prop của JobDetail (fixed init
 * job.output_format; switch MD/Word đã gỡ khỏi cả header + preview).
 */
export default function LayoutPreview({
  job,
  fmt,
}: {
  job: Job;
  fmt: "md-layout" | "docx-layout";
}) {
  const { t } = useT();
  const mode: Mode = fmt === "docx-layout" ? "word" : "md";
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
          const text = await blob.text();
          // markdown-it (html:false escape HTML thô) + DOMPurify — 2 tầng.
          setMdHtml(renderMdHtml(text));
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

  // U1 P0: job đổi → null html TRƯỚC (load() early-return khi state != null),
  // rồi load — CÙNG effect để không bao giờ có state null mà không refetch.
  // oxlint-disable-next-line react/set-state-in-effect
  useEffect(() => {
    setMdHtml(null);
    setWordHtml(null);
    void load(mode);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load theo mode+job.id, state check trong load
  }, [mode, job.id]);

  /** Wave-3 #7 → Lane I Task 4: "Lưu layout" dời sang UnifiedEditor (PATCH layout-content). */

  return (
    <section data-testid="layout-preview" className="flex min-w-0 flex-col gap-3">
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
            {t("common.retry")}
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
          title={t("preview.wordTitle")}
          sandbox=""
          // docStyle (body rule) + docx.html — srcdoc cùng origin iframe, sandbox off script.
          // Iframe không inherit tokens trang → inject :root --accent-text (dark + light)
          // để link color trong docStyle render đúng cả 2 theme (contrast-safe).
          srcDoc={`<style>:root { --accent-text: #58a6ff; }\n@media (prefers-color-scheme: light) { :root { --accent-text: #0861cf; } }</style><style>${wordBase}${docStyle}</style>${wordHtml ?? ""}`}
          className="h-[75vh] w-full rounded-md border border-border bg-surface"
        />
      )}
    </section>
  );
}
