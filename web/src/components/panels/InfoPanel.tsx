import type { Job } from "../../api/types";
import { STATUS_TEXT, STATUS_TONE } from "../../lib/status";
import IrViewer from "../IrViewer";
import Badge from "../ui/Badge";
import Card from "../ui/Card";

/** vi-VN datetime; null/absent → null. */
function fmt(iso: string | null | undefined): string | null {
  if (!iso) return null;
  return new Date(iso).toLocaleString("vi-VN");
}

/** Task 2: job metadata Card — status badge + timestamps + counts. */
export default function InfoPanel({ job }: { job: Job }) {
  const created = fmt(job.created_at);
  const started = fmt(job.started_at);
  const finished = fmt(job.finished_at);
  return (
    <Card testid="panel-info" title="Thông tin">
      <Badge
        tone={STATUS_TONE[job.status]}
        testid={`status-${job.id}`}
      >
        {STATUS_TEXT[job.status]}
      </Badge>
      <dl className="mt-2 space-y-1 text-sm">
        {created && (
          <div>
            <dt className="inline text-muted">Tạo lúc: </dt>
            <dd className="inline">{created}</dd>
          </div>
        )}
        {started && (
          <div>
            <dt className="inline text-muted">Bắt đầu: </dt>
            <dd className="inline">{started}</dd>
          </div>
        )}
        {finished && (
          <div>
            <dt className="inline text-muted">Hoàn thành: </dt>
            <dd className="inline">{finished}</dd>
          </div>
        )}
        <div>
          <dt className="inline text-muted">Số trang: </dt>
          <dd className="inline">{job.page_count}</dd>
        </div>
        {job.result && (
          <>
            <div>
              <dt className="inline text-muted">GPU (giây): </dt>
              <dd className="inline">{job.result.gpu_seconds}</dd>
            </div>
            <div>
              <dt className="inline text-muted">Model: </dt>
              <dd className="inline">{job.result.model_version}</dd>
            </div>
          </>
        )}
      </dl>
      {/* Spec #8: IR (JSON) collapsible — lazy fetch, status ≠ done → ẩn. */}
      <IrViewer jobId={job.id} status={job.status} />
    </Card>
  );
}
