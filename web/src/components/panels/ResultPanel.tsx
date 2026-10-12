import type { RefObject } from "react";
import type { Job, ResultBody } from "../../api/types";
import IssuesPanel from "../IssuesPanel";
import UnifiedEditor from "../UnifiedEditor";

/**
 * JD2 document-first reading column: unified "Soạn thảo" region (Plan M gộp
 * MarkdownEditor + PreviewTabs) → issues accordion. Stats line + ExportBar
 * nằm trong rail của JobDetail. Logic props giữ nguyên.
 */
export default function ResultPanel({
  jobId,
  job,
  result,
  editing,
  onEditingChange,
  hostRef,
}: {
  jobId: string;
  job: Job;
  result: ResultBody;
  editing: boolean;
  onEditingChange: (editing: boolean) => void;
  hostRef?: RefObject<HTMLElement | null>;
}) {
  const markdown = result.edited_markdown ?? result.markdown;
  return (
    <section data-testid="panel-result" className="flex min-w-0 flex-col gap-6">
      <UnifiedEditor
        jobId={jobId}
        job={job}
        markdown={markdown}
        editing={editing}
        onEditingChange={onEditingChange}
        hostRef={hostRef}
      />
      <IssuesPanel
        jobId={jobId}
        regions={result.pages.flatMap((p) => p.regions)}
        fileType={job.file_type}
      />
    </section>
  );
}
