import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { api } from "../api/client";
import type { ExtractionSaveResult } from "../api/types";
import { mapApiError } from "../lib/errors";
import { useT } from "../i18n";
import TextSection from "../components/TextSection";
import PageShell from "../components/PageShell";
import PageHeader from "../components/PageHeader";
import Button from "../components/ui/Button";

/**
 * Phase 2 (spec Sub-system B): trang trích xuất văn bản gốc.
 * WS-UI: toàn bộ highlight/popover/custom-save + IssuesPanel nằm trong
 * TextSection (dùng chung với JobDetail section "Văn bản"); trang này giữ
 * header + hint needs_render + "Vẽ lại layout".
 */
export default function ExtractionPage() {
  const { t } = useT();
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  /** Task 4: layouts không sync được trong lần save gần nhất → cần vẽ lại. */
  const [needsRender, setNeedsRender] = useState<string[]>([]);
  const [redrawing, setRedrawing] = useState(false);

  /** P2-3 review r1: file_type của job → TextSection (crop chỉ fetch khi "image"). */
  const { data: job } = useQuery({
    queryKey: ["job", id],
    queryFn: () => api.getJob(id!),
  });

  const handleRedraw = async () => {
    setRedrawing(true);
    try {
      await api.retryLayout(id!);
      setNeedsRender([]);
      toast.success(t("jd.retryLayoutDone"));
      await queryClient.invalidateQueries({ queryKey: ["job", id] });
    } catch (err) {
      toast.error(mapApiError(err));
    } finally {
      setRedrawing(false);
    }
  };

  return (
    <PageShell width="data">
      <PageHeader
        testid="extraction-header"
        title={<>{t("extraction.title")} <span className="font-mono">#{id}</span></>}
        beforeTitle={
          <Link
            to={`/jobs/${id}`}
            data-testid="link-back-job"
            className="inline-flex items-center gap-1 text-sm text-accent-text transition duration-150 ease-out hover:underline"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            {t("extraction.backToDetail")}
          </Link>
        }
      />

      {needsRender.length > 0 && (
        <div
          data-testid="needs-render-hint"
          role="alert"
          className="mb-4 flex flex-wrap items-center gap-3 rounded-md border border-warning/40 bg-warning/10 p-3 text-sm"
        >
          <TriangleAlert
            className="h-4 w-4 shrink-0 text-warning"
            aria-hidden="true"
          />
          <span className="min-w-0 flex-1">
            {t("extraction.needsRender")}
          </span>
          <Button
            testid="btn-redraw-layout"
            variant="primary"
            size="sm"
            loading={redrawing}
            disabled={redrawing}
            onClick={() => void handleRedraw()}
          >
            {t("jd.retryLayout")}
          </Button>
        </div>
      )}
      <TextSection
        jobId={id!}
        fileType={job?.file_type}
        onSaved={(result: ExtractionSaveResult) =>
          setNeedsRender(result.needs_render)
        }
      />
    </PageShell>
  );
}
