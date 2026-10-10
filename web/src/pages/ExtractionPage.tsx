import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { api, ApiError } from "../api/client";
import type { Suggestion } from "../api/types";
import { mapApiError } from "../lib/errors";
import { buildHighlights } from "../lib/highlight";
import Button from "../components/ui/Button";
import Skeleton from "../components/ui/Skeleton";

/**
 * Phase 2 (spec Sub-system B): trang trích xuất văn bản gốc.
 * Highlight phrase lỗi (proofread suggestions) → click → popover →
 * Áp dụng = POST /extraction (save + incremental sync, 0 LLM).
 */
export default function ExtractionPage() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const { data, isPending, isError } = useQuery({
    queryKey: ["extraction", id],
    queryFn: () => api.getExtraction(id!),
  });
  const { data: suggestions = [] } = useQuery({
    queryKey: ["suggestions", id],
    queryFn: () => api.getSuggestions(id!),
  });
  /** Mở theo đúng occurrence click (P1: repeat mark cũng mở được popover). */
  const [open, setOpen] = useState<{ sid: number; occ: number } | null>(null);
  const [savingSid, setSavingSid] = useState<number | null>(null);
  /** Task 4: layouts không sync được trong lần save gần nhất → cần vẽ lại. */
  const [needsRender, setNeedsRender] = useState<string[]>([]);
  const [redrawing, setRedrawing] = useState(false);

  const openSuggestion = suggestions.find((s) => s.id === open?.sid) ?? null;

  // P3: Escape + click-outside đóng popover.
  useEffect(() => {
    if (!openSuggestion) return;
    const close = () => setOpen(null);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    const onDown = (e: PointerEvent) => {
      if (!(e.target as HTMLElement).closest("[data-suggestion-anchor]"))
        close();
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onDown);
    };
  }, [openSuggestion]);

  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ["extraction", id] });
    await queryClient.invalidateQueries({ queryKey: ["job", id] });
    await queryClient.invalidateQueries({ queryKey: ["suggestions", id] });
  };

  const handleApply = async (s: Suggestion) => {
    if (!data) return;
    setSavingSid(s.id);
    // Server sync theo phrase (old→new, mọi occurrence) → text cũng replace
    // mọi occurrence để khớp layout sau sync.
    const newText = data.text.split(s.original).join(s.suggestion);
    const save = (force: boolean) =>
      api.saveExtraction(id!, {
        text: newText,
        old_phrase: s.original,
        new_phrase: s.suggestion,
        expected_text_version: data.text_version,
        ...(force ? { force: true } : {}),
      });
    try {
      let result;
      try {
        result = await save(false);
      } catch (err) {
        // P2: detached layout 409 → confirm ghi đè → resend force=true.
        const detached =
          err instanceof ApiError &&
          err.detail === "Layout có chỉnh tay. Đồng bộ sẽ ghi đè.";
        if (
          !detached ||
          !window.confirm("Layout có chỉnh tay. Đồng bộ sẽ ghi đè. Tiếp tục?")
        )
          throw err;
        result = await save(true);
      }
      setOpen(null);
      setNeedsRender(result.needs_render);
      toast.success(
        result.needs_render.length > 0
          ? "Đã lưu. Có layout cần vẽ lại."
          : "Đã lưu và đồng bộ layout.",
      );
      await invalidate();
    } catch (err) {
      // R59: toast + refresh optimistic lock (409) — không giữ version cũ trong UI.
      toast.error(mapApiError(err));
      setOpen(null);
      await invalidate();
    } finally {
      setSavingSid(null);
    }
  };

  const handleReject = async (s: Suggestion) => {
    try {
      await api.rejectSuggestion(id!, s.id);
      setOpen(null);
      await invalidate();
    } catch (err) {
      toast.error(mapApiError(err));
    }
  };

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
      {isPending && (
        <div data-testid="extraction-loading" className="flex flex-col gap-3">
          <Skeleton className="h-8 w-2/3" />
          <Skeleton className="h-24 w-full" />
        </div>
      )}
      {isError && (
        <p
          data-testid="extraction-error"
          role="alert"
          className="text-sm text-error"
        >
          Không tải được văn bản trích xuất.
        </p>
      )}
      {data && (
        <article
          data-testid="extraction-text"
          data-text-version={data.text_version}
          className="rounded-card border border-border bg-surface p-4 text-sm leading-[1.7] whitespace-pre-wrap shadow-card"
        >
          {buildHighlights(data.text, suggestions).map((seg, i) =>
            seg.sid === null ? (
              <span key={i}>{seg.text}</span>
            ) : (
              <span
                key={i}
                className="relative inline-block"
                data-suggestion-anchor
              >
                <mark
                  data-testid={
                    seg.occurrence
                      ? `suggestion-mark-${seg.sid}-${seg.occurrence}`
                      : `suggestion-mark-${seg.sid}`
                  }
                  className="rounded-sm bg-warning/20 underline decoration-dotted underline-offset-2"
                >
                  <button
                    type="button"
                    aria-expanded={
                      open?.sid === seg.sid && open?.occ === seg.occurrence
                    }
                    className="cursor-pointer bg-transparent px-0 text-inherit"
                    onClick={() =>
                      setOpen(
                        open?.sid === seg.sid && open?.occ === seg.occurrence
                          ? null
                          : { sid: seg.sid!, occ: seg.occurrence ?? 0 },
                      )
                    }
                  >
                    {seg.text}
                  </button>
                </mark>
                {open?.sid === seg.sid &&
                  open?.occ === (seg.occurrence ?? 0) &&
                  openSuggestion && (
                    <span
                      data-testid={`suggestion-popover-${seg.sid}`}
                      role="group"
                      aria-label="Gợi ý sửa"
                      className="absolute left-0 top-full z-20 mt-1 flex w-64 flex-col gap-2 rounded-md border border-border bg-surface p-3 shadow-card"
                    >
                      <span className="flex items-baseline gap-2">
                        <span className="text-sm line-through decoration-error text-error">
                          {openSuggestion.original}
                        </span>
                        <span className="text-sm text-success">
                          {openSuggestion.suggestion}
                        </span>
                      </span>
                      <span className="text-xs text-muted">
                        {openSuggestion.reason}
                      </span>
                      <span className="flex gap-2">
                        <Button
                          testid={`btn-apply-${seg.sid}`}
                          variant="primary"
                          size="sm"
                          loading={savingSid === seg.sid}
                          disabled={savingSid !== null}
                          onClick={() => void handleApply(openSuggestion)}
                        >
                          Áp dụng
                        </Button>
                        <Button
                          testid={`btn-reject-${seg.sid}`}
                          variant="ghost"
                          size="sm"
                          disabled={savingSid !== null}
                          onClick={() => void handleReject(openSuggestion)}
                        >
                          Bỏ qua
                        </Button>
                      </span>
                    </span>
                  )}
              </span>
            ),
          )}
        </article>
      )}
    </main>
  );
}
