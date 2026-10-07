import type { RefObject } from "react";
import type { ResultBody } from "../../api/types";
import IssuesPanel from "../IssuesPanel";
import MarkdownEditor from "../MarkdownEditor";
import PreviewTabs from "../PreviewTabs";

/**
 * JD2 document-first reading column: editor controls → preview (Tài liệu) →
 * issues accordion. Stats line + ExportBar chuyển sang rail của JobDetail
 * (meta thay vì nhồi cùng hàng với nội dung). Logic props giữ nguyên.
 */
export default function ResultPanel({
  jobId,
  result,
  editing,
  onEditingChange,
  hostRef,
}: {
  jobId: string;
  result: ResultBody;
  editing: boolean;
  onEditingChange: (editing: boolean) => void;
  hostRef?: RefObject<HTMLElement | null>;
}) {
  const markdown = result.edited_markdown ?? result.markdown;
  return (
    <section data-testid="panel-result" className="flex min-w-0 flex-col gap-6">
      <MarkdownEditor
        jobId={jobId}
        initial={markdown}
        editing={editing}
        onEditingChange={onEditingChange}
        hostRef={hostRef}
      />
      {/* Markdown preview moved to PreviewTabs (md tab default) — single preview-markdown. */}
      <PreviewTabs jobId={jobId} markdown={markdown} />
      <IssuesPanel jobId={jobId} regions={result.pages.flatMap((p) => p.regions)} />
    </section>
  );
}
