import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { api } from "../api/client";
import type { ExtractionSaveResult } from "../api/types";
import { mapApiError } from "../lib/errors";
import TextSection from "../components/TextSection";
import Button from "../components/ui/Button";

/**
 * Phase 2 (spec Sub-system B): trang trích xuất văn bản gốc.
 * WS-UI: toàn bộ highlight/popover/custom-save + IssuesPanel nằm trong
 * TextSection (dùng chung với JobDetail section "Văn bản"); trang này giữ
 * header + hint needs_render + "Vẽ lại layout".
 */
export default function ExtractionPage() {
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
      toast.success("Đã tạo lại layout.");
      await queryClient.invalidateQueries({ queryKey: ["job", id] });
    } catch (err) {
      toast.error(mapApiError(err));
    } finally {
      setRedrawing(false);
    }
  };

  return (
    <main id="main" className="mx-auto max-w-4xl p-4 sm:p-6">
      <header
        data-testid="extraction-header"
        className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2"
      >
        <Link
          to={`/jobs/${id}`}
          data-testid="link-back-job"
          className="inline-flex items-center gap-1 text-sm text-accent-text transition duration-150 ease-out hover:underline"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          Về chi tiết công việc
        </Link>
        <h1 className="text-xl font-bold tracking-tight sm:text-2xl">
          Trích xuất văn bản <span className="font-mono">#{id}</span>
        </h1>
      </header>

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
            Một số layout chưa đồng bộ được. Vẽ lại layout để cập nhật bản mới
            nhất.
          </span>
          <Button
            testid="btn-redraw-layout"
            variant="primary"
            size="sm"
            loading={redrawing}
            disabled={redrawing}
            onClick={() => void handleRedraw()}
          >
            Vẽ lại layout
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
    </main>
  );
}
