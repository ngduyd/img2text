import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { api, ApiError } from "../api/client";
import type { ExtractionSaveResult, RegionOut, Suggestion } from "../api/types";
import { mapApiError } from "../lib/errors";
import { buildHighlights } from "../lib/highlight";
import IssuesPanel from "./IssuesPanel";
import Button from "./ui/Button";
import Skeleton from "./ui/Skeleton";
import { useDialogA11y } from "./ui/useDialogA11y";

/**
 * WS-UI section "Văn bản": text render HTML thuần (GET /extraction, không
 * free editor) + highlight proofread → popover [Áp dụng][Bỏ qua] + ô nhập
 * "Sửa khác…" (custom phrase → POST /extraction). Panel "Kiểm tra lỗi"
 * (IssuesPanel) nằm DƯỚI text. Section hiện cả khi status == "rendering"
 * (GET /extraction cho phép rendering — OCR xong).
 */

/** w-64 popover: chạm mép phải viewport (rect.right + 256) → flip right-0; max-w chặn tràn. */
function popoverPos(anchor: HTMLElement | undefined): string {
  const rect = anchor?.getBoundingClientRect();
  return rect && rect.right + 256 > window.innerWidth ? "right-0 left-auto" : "left-0";
}

export default function TextSection({
  jobId,
  regions,
  fileType,
  onSaved,
}: {
  jobId: string;
  regions?: RegionOut[];
  fileType?: string;
  onSaved?: (result: ExtractionSaveResult) => void;
}) {
  const queryClient = useQueryClient();
  const { data, isPending, isError } = useQuery({
    queryKey: ["extraction", jobId],
    queryFn: () => api.getExtraction(jobId),
  });
  const { data: suggestions = [] } = useQuery({
    queryKey: ["suggestions", jobId],
    queryFn: () => api.getSuggestions(jobId),
  });
  /** Mở theo đúng occurrence click (P1: repeat mark cũng mở được popover). */
  const [open, setOpen] = useState<{ sid: number; occ: number } | null>(null);
  const [savingSid, setSavingSid] = useState<number | null>(null);
  /** Custom phrase "Sửa khác…" — value theo sid đang mở. */
  const [customText, setCustomText] = useState("");
  /** Task 6: save set cờ rerender (rendering | sync targeted-fail) → confirm xếp hàng. */
  const [rerenderModal, setRerenderModal] = useState(false);
  const rerenderPanelRef = useDialogA11y<HTMLDivElement>(rerenderModal, () =>
    setRerenderModal(false),
  );

  const openSuggestion = suggestions.find((s) => s.id === open?.sid) ?? null;
  /** Anchor element per suggestion key — popover flip đọc rect từ đây lúc render. */
  const anchorEls = useRef(new Map<string, HTMLSpanElement>());

  // P2: resize/scroll while open → popoverPos recompute (rect tính lúc render, stale nếu không bump).
  const [, setPopoverTick] = useState(0);
  useEffect(() => {
    if (!openSuggestion) return;
    const bump = () => setPopoverTick((n) => n + 1);
    // capture=true: scroll của ancestor container cũng đổi vị trí tương đối viewport.
    window.addEventListener("resize", bump);
    window.addEventListener("scroll", bump, true);
    return () => {
      window.removeEventListener("resize", bump);
      window.removeEventListener("scroll", bump, true);
    };
  }, [openSuggestion]);

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
    await queryClient.invalidateQueries({ queryKey: ["extraction", jobId] });
    await queryClient.invalidateQueries({ queryKey: ["job", jobId] });
    await queryClient.invalidateQueries({ queryKey: ["suggestions", jobId] });
  };

  /** POST /extraction (old→new phrase) → save + sync; detached 409 → force resend. */
  const saveReplace = async (original: string, replacement: string) => {
    if (!data) return;
    // Server sync theo phrase (old→new, mọi occurrence) → text cũng replace
    // mọi occurrence để khớp layout sau sync.
    const newText = data.text.split(original).join(replacement);
    const save = (force: boolean) =>
      api.saveExtraction(jobId, {
        text: newText,
        old_phrase: original,
        new_phrase: replacement,
        expected_text_version: data.text_version,
        ...(force ? { force: true } : {}),
      });
    try {
      let result: ExtractionSaveResult;
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
      setCustomText("");
      // Task 6: response requires_rerender (hoặc status rendering — server set cờ)
      // → modal confirm "Thêm vào hàng đợi?"; chưa thì toast sync như cũ.
      if (result.requires_rerender) {
        setRerenderModal(true);
      } else {
        toast.success(
          result.needs_render.length > 0
            ? "Đã lưu. Có layout cần vẽ lại."
            : "Đã lưu và đồng bộ layout.",
        );
      }
      await invalidate();
      onSaved?.(result);
    } catch (err) {
      // R59: toast + refresh optimistic lock (409) — không giữ version cũ trong UI.
      toast.error(mapApiError(err));
      setOpen(null);
      await invalidate();
    } finally {
      setSavingSid(null);
    }
  };

  const handleApply = (s: Suggestion) => {
    setSavingSid(s.id);
    void saveReplace(s.original, s.suggestion);
  };

  const handleReject = async (s: Suggestion) => {
    try {
      await api.rejectSuggestion(jobId, s.id);
      setOpen(null);
      await invalidate();
    } catch (err) {
      toast.error(mapApiError(err));
    }
  };

  const handleCustom = (s: Suggestion) => {
    if (!customText.trim()) return;
    setSavingSid(s.id);
    void saveReplace(s.original, customText);
  };

  return (
    <div className="flex min-w-0 flex-col gap-6">
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
          {buildHighlights(data.text, suggestions).map((seg, i) => {
            if (seg.sid === null) return <span key={i}>{seg.text}</span>;
            const anchorKey = `${seg.sid}-${seg.occurrence ?? 0}`;
            return (
              <span
                key={i}
                className="relative inline-block"
                data-suggestion-anchor
                ref={(el) => {
                  if (el) anchorEls.current.set(anchorKey, el);
                  else anchorEls.current.delete(anchorKey);
                }}
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
                      className={`absolute top-full z-20 mt-1 flex w-64 max-w-[calc(100vw-2rem)] flex-col gap-2 rounded-md border border-border bg-surface p-3 shadow-card ${popoverPos(
                        anchorEls.current.get(anchorKey),
                      )}`}
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
                          onClick={() => handleApply(openSuggestion)}
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
                      {/* WS-UI: ô nhập "Sửa khác…" — custom phrase → POST /extraction. */}
                      <label
                        htmlFor={`custom-${seg.sid}`}
                        className="text-xs font-medium text-muted"
                      >
                        Sửa khác…
                      </label>
                      <span className="flex gap-2">
                        <input
                          id={`custom-${seg.sid}`}
                          data-testid={`input-custom-${seg.sid}`}
                          type="text"
                          value={customText}
                          onChange={(e) => setCustomText(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") handleCustom(openSuggestion);
                          }}
                          placeholder={openSuggestion.original}
                          className="min-w-0 flex-1 rounded-md border border-border bg-surface px-2 py-1 text-sm text-text focus-visible:outline-2 focus-visible:outline-accent"
                        />
                        <Button
                          testid={`btn-save-custom-${seg.sid}`}
                          variant="secondary"
                          size="sm"
                          loading={savingSid === seg.sid}
                          disabled={savingSid !== null || !customText.trim()}
                          onClick={() => handleCustom(openSuggestion)}
                        >
                          Lưu
                        </Button>
                      </span>
                    </span>
                  )}
              </span>
            );
          })}
        </article>
      )}
      {/* WS-UI Task 6: confirm modal queue (useDialogA11y — Escape/ref focus). */}
      {rerenderModal && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/50 p-4">
          <div
            ref={rerenderPanelRef}
            tabIndex={-1}
            data-testid="rerender-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="rerender-modal-title"
            className="w-full max-w-md rounded-card border border-border bg-surface p-4 shadow-card focus-visible:outline-2 focus-visible:outline-accent"
          >
            <p id="rerender-modal-title" className="text-sm font-medium">
              Lưu văn bản sẽ cần vẽ lại layout. Thêm vào hàng đợi vẽ layout?
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <Button
                testid="btn-rerender-cancel"
                variant="ghost"
                onClick={() => setRerenderModal(false)}
              >
                Hủy
              </Button>
              <Button
                testid="btn-rerender-confirm"
                onClick={() => {
                  setRerenderModal(false);
                  toast.success("Đã xếp hàng vẽ lại layout.");
                }}
              >
                Lưu & xếp hàng
              </Button>
            </div>
          </div>
        </div>
      )}
      {/* WS-UI: panel "Kiểm tra lỗi" chuyển vào section Văn bản (dưới text). */}
      {/* P2-3: fileType unknown (route trích xuất chưa fetch job) → KHÔNG default
          "image": IssuesPanel chỉ fetch crop khi đúng "image". */}
      {regions != null && (
        <IssuesPanel
          jobId={jobId}
          regions={regions}
          fileType={fileType}
        />
      )}
    </div>
  );
}
