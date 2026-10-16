import { useQuery, useQueryClient } from "@tanstack/react-query";
import { EditorContent, useEditor } from "@tiptap/react";
import { Fragment, Slice } from "@tiptap/pm/model";
import type { EditorView } from "@tiptap/pm/view";
import type { CSSProperties } from "react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { toast } from "sonner";
import { api, ApiError } from "../api/client";
import type { ExtractionSaveResult, RegionOut, Suggestion } from "../api/types";
import { mapApiError } from "../lib/errors";
import { buildHighlights } from "../lib/highlight";
import { translate, useT } from "../i18n";
import { wordExtensions } from "../lib/wordEditor";
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

/** U9: popover portaled (fixed ra body — không clip overflow ancestor) → tọa độ từ anchor rect. */
function popoverStyle(anchor: HTMLElement | undefined): CSSProperties {
  const rect = anchor?.getBoundingClientRect();
  if (!rect) return { top: 0, left: 0 };
  return rect.right + 256 > window.innerWidth
    ? { top: rect.bottom, right: Math.max(8, window.innerWidth - rect.right) }
    : { top: rect.bottom, left: rect.left };
}

/** Escape text thường trước khi nhét làm HTML content của Tiptap. */
const escapeHtml = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

/**
 * Lane I Task 1: dán từ Word → preventDefault + chỉ chèn text/plain (mỗi dòng
 * 1 paragraph, bỏ formatting HTML). PASTE STRIP. Module-level để setOptions
 * (lane M3 P2 aria-label update) không mất handler.
 */
function stripPaste(view: EditorView, event: ClipboardEvent): boolean {
  const plain = event.clipboardData?.getData("text/plain");
  if (plain == null) return false;
  // Review r1 P2f: plain rỗng cũng preventDefault + chèn "" — không rơi về HTML default.
  event.preventDefault();
  const frag = Fragment.fromArray(
    plain
      .replace(/\r\n?/g, "\n")
      .split("\n")
      .map((line) =>
        view.state.schema.nodes.paragraph.create(
          null,
          line ? view.state.schema.text(line) : null,
        ),
      ),
  );
  // Không .scrollIntoView(): jsdom thiếu getClientRects (crash PM scrollToSelection).
  view.dispatch(view.state.tr.replaceSelection(new Slice(frag, 0, 0)));
  return true;
}

/**
 * Lane I Task 1: soạn thảo thuần text — Tiptap (wordExtensions đã có), mỗi dòng
 * = 1 paragraph; PASTE STRIP: dán từ Word → preventDefault + chỉ chèn
 * text/plain (mỗi dòng 1 paragraph, bỏ mọi formatting HTML).
 */
function TextEditor({
  text,
  saving,
  onSave,
}: {
  text: string;
  saving: boolean;
  onSave: (text: string) => void;
}) {
  const { t, lang } = useT();
  const editor = useEditor({
    extensions: wordExtensions,
    content: text
      // Review r1 P2a: split("\n") GIỮ empty lines (round-trip save/ load nguyên vẹn).
      .split("\n")
      .map((p) => `<p>${escapeHtml(p)}</p>`)
      .join(""),
    editorProps: {
      // Review r1 P2b: contenteditable cần accessible name.
      attributes: { "aria-label": translate("editor.textAreaAria") },
      handlePaste: stripPaste,
    },
  });
  // Lane M3 P2: aria-label translate() lúc init chỉ snapshot 1 lần — setOptions khi lang đổi.
  useEffect(() => {
    if (!editor) return;
    editor.setOptions({
      editorProps: {
        attributes: { "aria-label": translate("editor.textAreaAria") },
        handlePaste: stripPaste,
      },
    });
  }, [editor, lang]);
  return (
    <div className="flex flex-col gap-3">
      <div
        data-testid="text-editor"
        className="rounded-card border border-border bg-surface p-4 shadow-card"
      >
        <EditorContent editor={editor} />
      </div>
      <div className="flex justify-end">
        <Button
          testid="btn-save-text"
          loading={saving}
          disabled={!editor}
          onClick={() => editor && onSave(editor.getText({ blockSeparator: "\n" }))}
        >
          {t("common.save")}
        </Button>
      </div>
    </div>
  );
}

export default function TextSection({
  jobId,
  regions,
  fileType,
  onSaved,
  editingText: editingTextProp,
  onEditingTextChange,
}: {
  jobId: string;
  regions?: RegionOut[];
  fileType?: string;
  onSaved?: (result: ExtractionSaveResult) => void;
  /** U2: controlled từ JobDetail (nút Edit ở heading row); thiếu prop → internal (ExtractionPage). */
  editingText?: boolean;
  onEditingTextChange?: (editing: boolean) => void;
}) {
  const { t } = useT();
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
  /** P2-5: Lưu khi rỗng → lỗi inline (role="alert" + aria-describedby). */
  const [customError, setCustomError] = useState(false);
  /** Lane I Task 1: toggle "Soạn thảo" — sửa tay thuần text (Tiptap) song song click-fix.
   *  U2: JobDetail control qua prop; không prop → internal state (fallback). */
  const [editingTextInternal, setEditingTextInternal] = useState(false);
  const editingText = editingTextProp ?? editingTextInternal;
  const setEditingText = onEditingTextChange ?? setEditingTextInternal;
  const [savingText, setSavingText] = useState(false);
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
      const target = e.target as HTMLElement;
      // U9: popover portaled khỏi anchor → cho phép click bên trong popover (apply/reject/custom).
      if (!target.closest("[data-suggestion-anchor], [data-suggestion-popover]"))
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
        // Lane M3 P1b: server gửi detail {code:"detached"} — so theo code,
        // fallback detail string cũ (backward compat server cũ).
        const detached =
          err instanceof ApiError &&
          (err.code === "detached" ||
            err.detail === "Layout có chỉnh tay. Đồng bộ sẽ ghi đè.");
        if (!detached || !window.confirm(t("editor.detachedConfirm")))
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
            ? t("editor.savedNeedsRender")
            : t("editor.savedSynced"),
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
    if (!customText.trim()) {
      setCustomError(true);
      return;
    }
    setCustomError(false);
    setSavingSid(s.id);
    void saveReplace(s.original, customText);
  };

  /** Lane I Task 1: lưu toàn bộ text soạn tay (không old/new phrase — full save). */
  const saveFullText = async (text: string) => {
    if (!data) return;
    setSavingText(true);
    try {
      await api.saveExtraction(jobId, {
        text,
        expected_text_version: data.text_version,
      });
      setEditingText(false);
      toast.success(t("editor.saved"));
      await invalidate();
    } catch (err) {
      toast.error(mapApiError(err));
    } finally {
      setSavingText(false);
    }
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
          {t("editor.loadError")}
        </p>
      )}
      {data && (
        <>
          {/* U2: controlled (JobDetail) → nút Edit nằm heading row ngoài này; uncontrolled giữ nút nội bộ. */}
          {onEditingTextChange === undefined && (
            <div className="flex justify-end">
              <Button
                testid="btn-edit-text"
                variant="secondary"
                aria-pressed={editingText}
                onClick={() => setEditingText(!editingText)}
              >
                {editingText ? t("editor.editing") : t("editor.edit")}
              </Button>
            </div>
          )}
          {editingText ? (
            <TextEditor
              text={data.text}
              saving={savingText}
              onSave={(text) => void saveFullText(text)}
            />
          ) : (
        <div className="max-h-[75vh] overflow-y-auto">
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
                  openSuggestion &&
                  createPortal(
                    <span
                      data-testid={`suggestion-popover-${seg.sid}`}
                      data-suggestion-popover
                      role="group"
                      aria-label={t("editor.suggestionAria")}
                      className={`fixed z-20 mt-1 flex w-64 max-w-[calc(100vw-2rem)] flex-col gap-2 rounded-md border border-border bg-surface p-3 shadow-card ${popoverPos(
                        anchorEls.current.get(anchorKey),
                      )}`}
                      style={popoverStyle(anchorEls.current.get(anchorKey))}
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
                          {t("editor.apply")}
                        </Button>
                        <Button
                          testid={`btn-reject-${seg.sid}`}
                          variant="ghost"
                          size="sm"
                          disabled={savingSid !== null}
                          onClick={() => void handleReject(openSuggestion)}
                        >
                          {t("editor.reject")}
                        </Button>
                      </span>
                      {/* WS-UI: ô nhập "Sửa khác…" — custom phrase → POST /extraction. */}
                      <label
                        htmlFor={`custom-${seg.sid}`}
                        className="text-xs font-medium text-muted"
                      >
                        {t("editor.customOther")}
                      </label>
                      <span className="flex gap-2">
                        <input
                          id={`custom-${seg.sid}`}
                          data-testid={`input-custom-${seg.sid}`}
                          type="text"
                          value={customText}
                          onChange={(e) => {
                            setCustomText(e.target.value);
                            setCustomError(false);
                          }}
                          aria-invalid={customError || undefined}
                          aria-describedby={
                            customError ? `custom-error-${seg.sid}` : undefined
                          }
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
                          disabled={savingSid !== null}
                          onClick={() => handleCustom(openSuggestion)}
                        >
                          {t("common.save")}
                        </Button>
                      </span>
                      {/* P2-5: lỗi validate rỗng — alert + describedby cho input. */}
                      {customError && (
                        <p
                          id={`custom-error-${seg.sid}`}
                          data-testid={`custom-error-${seg.sid}`}
                          role="alert"
                          className="text-xs text-error"
                        >
                          {t("editor.emptyContent")}
                        </p>
                      )}
                    </span>,
                    document.body,
                  )}
              </span>
            );
          })}
        </article>
        </div>
          )}
        </>
      )}
      {/* WS-UI Task 6: confirm modal queue (useDialogA11y — Escape/ref focus). */}
      {rerenderModal && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-overlay p-4">
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
              {t("editor.rerenderQuestion")}
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <Button
                testid="btn-rerender-cancel"
                variant="ghost"
                onClick={() => setRerenderModal(false)}
              >
                {t("common.cancel")}
              </Button>
              <Button
                testid="btn-rerender-confirm"
                onClick={() => {
                  setRerenderModal(false);
                  toast.success(t("editor.rerenderQueued"));
                }}
              >
                {t("editor.saveAndQueue")}
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
