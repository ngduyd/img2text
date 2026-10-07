import { useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ApiError, api } from "../api/client";
import { mapApiError } from "../lib/errors";
import MdToolbar from "./editor/MdToolbar";
import type { MdFormatOp, MdHistory } from "./editor/mdFormat";
import { applyMdOp } from "./editor/mdFormat";
import Button from "./ui/Button";

/**
 * Trạng thái `editing` controlled từ trang JobDetail (btn-edit-doc = entry
 * duy nhất để vào edit); state chưa editing = preview read-only + hint, không
 * nút. Save logic giữ nguyên (PATCH + invalidate job).
 */
export default function MarkdownEditor({
  jobId,
  initial,
  editing,
  onEditingChange,
  hostRef,
}: {
  jobId: string;
  initial: string;
  editing: boolean;
  onEditingChange: (editing: boolean) => void;
  hostRef?: RefObject<HTMLElement | null>;
}) {
  const [value, setValue] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<MdHistory>({ past: [], future: [] });
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const wasEditing = useRef(editing);
  const queryClient = useQueryClient();

  // Vào edit (btn-edit-doc) → nạp draft từ markdown mới nhất.
  useEffect(() => {
    if (editing && !wasEditing.current) {
      setValue(initial);
      setError(null);
      setHistory({ past: [], future: [] });
    }
    wasEditing.current = editing;
  }, [editing, initial]);

  const save = async () => {
    setError(null);
    try {
      await api.patchContent(jobId, value);
      toast.success("Đã lưu.");
      onEditingChange(false);
      // Binding (T5 ledger): invalidate job query or preview shows stale
      // edited_markdown (polling stopped at done).
      await queryClient.invalidateQueries({ queryKey: ["job", jobId] });
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Lưu thất bại.");
      toast.error(mapApiError(err));
    }
  };

  /** Toolbar → applyMdOp (contract Edit2) → setValue + khôi phục selection sau render (rAF). */
  const handleFormat = (op: MdFormatOp, arg?: string) => {
    const ta = textareaRef.current;
    if (!ta) return;
    const res = applyMdOp(value, ta.selectionStart, ta.selectionEnd, op, history, arg);
    setValue(res.value);
    setHistory({ past: res.past, future: res.future });
    requestAnimationFrame(() => {
      ta.focus();
      ta.setSelectionRange(res.start, res.end);
    });
  };

  return (
    /* scroll-mt-32: offset qua sticky header job (top-14/md:top-16 + header) khi btn-edit-doc scroll tới. */
    <section ref={hostRef} className="scroll-mt-32">
      {error && (
        <div
          data-testid="editor-error"
          className="mb-2 rounded-md border border-error/40 bg-error/10 px-3 py-2 text-error"
        >
          {error}
        </div>
      )}
      {editing && <MdToolbar onFormat={handleFormat} />}
      {editing && (
        <textarea
          ref={textareaRef}
          data-testid="textarea-markdown"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="mb-2 h-64 w-full rounded-md border border-border bg-surface p-2 font-mono text-sm leading-[1.6] text-text"
        />
      )}
      {editing ? (
        <div className="flex gap-2">
          <Button testid="btn-save" onClick={save}>
            Lưu
          </Button>
        </div>
      ) : (
        /* Chưa editing: preview nguồn read-only (PreviewTabs loa rendered) + hint. */
        <div>
          <div
            data-testid="md-source-preview"
            className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-card border border-border bg-surface p-3 font-mono text-sm text-text"
          >
            {initial}
          </div>
          <p data-testid="md-edit-hint" className="mt-2 text-xs text-muted">
            Nhấn Edit ở trên để sửa nội dung.
          </p>
        </div>
      )}
    </section>
  );
}
