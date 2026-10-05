import type { ResultBody, ResultPage, Verdict } from "../../api/types";
import ExportBar from "../ExportBar";
import IssuesPanel from "../IssuesPanel";
import MarkdownEditor from "../MarkdownEditor";
import PreviewTabs from "../PreviewTabs";
import Card from "../ui/Card";

/** Task 2 verdict stats — counts keyed by RegionOut.verdict (VERDICT_LABELS keys). */
function statsLine(pages: ResultPage[]): string {
  const regions = pages.flatMap((p) => p.regions);
  const count = (v: Verdict) => regions.filter((r) => r.verdict === v).length;
  return (
    `Tổng ${regions.length} vùng · ${count("ok")} ok · ` +
    `${count("image_unextractable")} hình ảnh · ${count("unreadable")} không trích xuất · ` +
    `${count("low_confidence")} cần kiểm tra`
  );
}

/** Task 2: result Card — editor + stats + preview + issues + export. */
export default function ResultPanel({
  jobId,
  result,
}: {
  jobId: string;
  result: ResultBody;
}) {
  const markdown = result.edited_markdown ?? result.markdown;
  return (
    <>
      <Card
        testid="panel-result"
        title="Kết quả"
        actions={<MarkdownEditor jobId={jobId} initial={markdown} />}
      >
        {/* Editor in Card header slot (binding plan line 79): btn-edit stays prominent. */}
        <p data-testid="result-stats" className="mb-2 text-sm text-muted">
          {statsLine(result.pages)}
        </p>
        {/* Markdown preview moved to PreviewTabs (md tab default) — single preview-markdown. */}
        <IssuesPanel jobId={jobId} regions={result.pages.flatMap((p) => p.regions)} />
        <div className="mt-4">
          <ExportBar jobId={jobId} />
        </div>
      </Card>
      {/* Task 5: separate Card AFTER ExportBar — preview tabs (md/pdf/docx). */}
      <PreviewTabs jobId={jobId} markdown={markdown} />
    </>
  );
}
