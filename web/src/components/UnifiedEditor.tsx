import { useQueryClient } from "@tanstack/react-query";
import DOMPurify from "dompurify";
import * as mammoth from "mammoth";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { RefObject } from "react";
import { toast } from "sonner";
import { api } from "../api/client";
import type { Job, LayoutStyle } from "../api/types";
import { buildLayoutStyleCss } from "../lib/docStyle";
import { mapApiError } from "../lib/errors";
import DocStyleTools from "./DocStyleTools";
import MdToolbar from "./editor/MdToolbar";
import type { MdFormatOp, MdHistory } from "./editor/mdFormat";
import { applyMdOp } from "./editor/mdFormat";
import WordEditor from "./editor/WordEditor";
import MarkdownPreview from "./MarkdownPreview";
import Badge from "./ui/Badge";
import Button from "./ui/Button";
import Card from "./ui/Card";
import Skeleton from "./ui/Skeleton";

type Mode = "md" | "word";

const FMT: Record<Mode, "md-layout" | "docx-layout"> = { md: "md-layout", word: "docx-layout" };

/**
 * Plan M region "Soạn thảo" (gộp card "Tài liệu" + MarkdownEditor cũ; R51:
 * testids preview-markdown/preview-docx-frame giữ, tabs preview-md/preview-docx,
 * panel-docs, md-source-preview/md-edit-hint, btn-llm-layout-* gỡ).
 *
 * Flow per mode: exportJob(fmt) → downloadExport(fmt) → render. exportJob TỰ
 * gọi LLM khi layout_cache miss, cache-hit trả về nhanh không tốn LLM, nên
 * một đường duy nhất cho cả 2 nhánh. ponytail: nếu sau này cần chặn request
 * khi cache-hit thì mới tách nhánh theo job.layout_cache (lúc đó badge cũng
 * thôi là nguồn sự thật).
 */
export default function UnifiedEditor({
  jobId,
  job,
  markdown,
  editing,
  onEditingChange,
  hostRef,
}: {
  jobId: string;
  job: Job;
  markdown: string;
  editing: boolean;
  onEditingChange: (editing: boolean) => void;
  hostRef?: RefObject<HTMLElement | null>;
}) {
  const queryClient = useQueryClient();
  // Binding: default mode theo output_format chọn lúc upload.
  const [mode, setMode] = useState<Mode>(job.output_format === "docx" ? "word" : "md");
  // Plan M3: docx.html cache (PUT html lần trước) → load thẳng, bỏ mammoth/export.
  const docxHtmlCached = job.layout_cache?.docx_html === true;
  // md text = artifact md-layout; markdown prop chỉ là nội dung tạm trước khi artifact về.
  const [mdText, setMdText] = useState(markdown);
  const [docxHtml, setDocxHtml] = useState<string | null>(null);
  const [loaded, setLoaded] = useState({ md: false, word: false });
  const [error, setError] = useState<{ mode: Mode; message: string } | null>(null);
  // Md source edit (handleFormat pattern từ MarkdownEditor cũ, nguồn = md-layout).
  const [history, setHistory] = useState<MdHistory>({ past: [], future: [] });
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  // Word style: css bắn vào iframe sống, styleMap là bản PUT layout-style.
  const [baseCss, setBaseCss] = useState("");
  const [wordCss, setWordCss] = useState("");
  const [styleMap, setStyleMap] = useState<LayoutStyle | null>(null);

  // layout_style đã lưu → client CSS cho md iframe (word iframe tái tạo từ tools hydrate).
  const savedCss = useMemo(() => buildLayoutStyleCss(job.layout_style), [job.layout_style]);

  const runFlow = useCallback(
    async (m: Mode) => {
      try {
        // Plan M3: word content đã lưu (layout_cache.docx_html) → GET docx.html,
        // không exportJob (không tốn LLM) + không mammoth; 404 → fallback bên dưới.
        const cachedHtml = m === "word" && docxHtmlCached ? await api.getDocxHtml(jobId) : null;
        if (cachedHtml !== null) {
          setDocxHtml(DOMPurify.sanitize(cachedHtml));
        } else {
          await api.exportJob(jobId, FMT[m]);
          const blob = await api.downloadExport(jobId, FMT[m]);
          if (m === "md") {
            setMdText(await blob.text());
          } else {
            const { value } = await mammoth.convertToHtml({ arrayBuffer: await blob.arrayBuffer() });
            // mammoth output untrusted → DOMPurify trước khi srcdoc (script bị strip).
            setDocxHtml(DOMPurify.sanitize(value));
          }
        }
        setLoaded((prev) => ({ ...prev, [m]: true }));
        // Retry thành công / vào lại mode lỗi → dọn error của mode này (async, sau await).
        setError((prev) => (prev?.mode === m ? null : prev));
      } catch (err) {
        setError({ mode: m, message: mapApiError(err) });
        toast.error(mapApiError(err));
      }
    },
    [jobId, docxHtmlCached],
  );

  /*
   * btn-edit-doc (header) = entry duy nhất để vào sửa nguồn: luôn hiện md mode.
   * Derive thay vì setState-in-effect (oxlint set-state-in-effect): editing=true
   * → activeMode md, không cần effect ép mode.
   */
  const activeMode: Mode = editing ? "md" : mode;
  const displayError = error?.mode === activeMode ? error.message : null;
  // Loading derived: chưa load xong cho mode hiện tại và không có error đang hiện.
  const loading = !loaded[activeMode] && displayError === null;

  // Auto-load khi mount hoặc đổi mode (chưa loaded mới chạy; loaded → giữ nguyên).
  useEffect(() => {
    // setState trong runFlow nằm SAU await (async continuation), không cascade render đồng bộ.
    // oxlint-disable-next-line react/set-state-in-effect
    if (!loaded[activeMode]) void runFlow(activeMode);
  }, [activeMode, loaded, runFlow]);

  // Vào edit → scroll mượt tới vùng Soạn thảo (scroll-mt-32 tránh sticky header).
  useEffect(() => {
    if (!editing) return;
    hostRef?.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [editing, hostRef]);

  // Focus textarea khi editing (render md mode → có textarea).
  useEffect(() => {
    if (editing) hostRef?.current?.querySelector("textarea")?.focus();
  });

  const switchMode = (m: Mode) => {
    if (m === activeMode) return;
    setMode(m);
    // Nguồn md-layout chỉ sửa ở md mode; sang word → đóng source edit.
    if (m === "word" && editing) onEditingChange(false);
  };

  const saveLayout = async () => {
    try {
      await api.putMdLayoutContent(jobId, mdText);
      toast.success("Đã lưu.");
      // Flag layout_cache đổi phía server → refresh job để badge cập nhật.
      await queryClient.invalidateQueries({ queryKey: ["job", jobId] });
    } catch (err) {
      toast.error(mapApiError(err));
    }
  };

  const saveStyle = async () => {
    try {
      await api.putLayoutStyle(jobId, styleMap);
      toast.success("Đã lưu.");
    } catch (err) {
      toast.error(mapApiError(err));
    }
  };

  /** Plan M4: editor.getHTML() (Tiptap) → PUT docx.html → toast + refresh layout_cache. */
  const saveWord = async (html: string) => {
    try {
      await api.putDocxHtml(jobId, html);
      toast.success("Đã lưu.");
      // Flag layout_cache.docx_html đổi phía server → refresh job (badge + load sau).
      await queryClient.invalidateQueries({ queryKey: ["job", jobId] });
    } catch (err) {
      toast.error(mapApiError(err));
    }
  };

  /** Toolbar → applyMdOp (contract Edit2) → setValue + khôi phục selection sau render (rAF). */
  const handleFormat = (op: MdFormatOp, arg?: string) => {
    const ta = textareaRef.current;
    if (!ta) return;
    const res = applyMdOp(mdText, ta.selectionStart, ta.selectionEnd, op, history, arg);
    setMdText(res.value);
    setHistory({ past: res.past, future: res.future });
    requestAnimationFrame(() => {
      ta.focus();
      ta.setSelectionRange(res.start, res.end);
    });
  };

  const cached = (job.layout_cache ?? { md: false, docx: false })[
    activeMode === "md" ? "md" : "docx"
  ];

  return (
    /* scroll-mt-32: offset qua sticky header job khi btn-edit-doc scroll tới. */
    <section ref={hostRef} className="scroll-mt-32">
      <Card testid="panel-editor" title="Soạn thảo">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div
            role="group"
            aria-label="Chế độ soạn thảo"
            className="inline-flex items-center gap-1 rounded-md border border-border p-1"
          >
            <Button
              testid="switch-mode-md"
              variant="ghost"
              size="sm"
              aria-pressed={activeMode === "md"}
              className={activeMode === "md" ? "bg-surface-2 font-semibold" : ""}
              onClick={() => switchMode("md")}
            >
              Markdown
            </Button>
            <Button
              testid="switch-mode-word"
              variant="ghost"
              size="sm"
              aria-pressed={activeMode === "word"}
              className={activeMode === "word" ? "bg-surface-2 font-semibold" : ""}
              onClick={() => switchMode("word")}
            >
              Word
            </Button>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge testid="layout-badge" tone={cached ? "success" : "neutral"}>
              {cached ? "Layout đã lưu" : "Layout chưa lưu"}
            </Badge>
            {activeMode === "md" && (
              <Button
                testid="btn-edit-source"
                variant="secondary"
                size="sm"
                aria-pressed={editing}
                onClick={() => onEditingChange(!editing)}
              >
                Chỉnh sửa nguồn
              </Button>
            )}
          </div>
        </div>
        {displayError !== null && (
          <div
            data-testid="layout-error"
            role="alert"
            className="mb-2 flex flex-wrap items-center gap-3 rounded-md border border-error/40 bg-error/10 px-3 py-2 text-error"
          >
            <span className="min-w-0 flex-1 break-words">{displayError}</span>
            <Button
              testid="btn-retry-layout"
              variant="secondary"
              size="sm"
              onClick={() => {
                setError(null);
                void runFlow(activeMode);
              }}
            >
              Thử lại
            </Button>
          </div>
        )}
        {loading ? (
          /* Loading khớp hình content area thật (skeleton, không spinner tròn). */
          <div
            data-testid="layout-loading"
            role="status"
            className="flex flex-col gap-2 rounded-md border border-border bg-surface-2 p-3"
          >
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-96 w-full" />
            <p className="text-sm text-muted">Đang vẽ layout bằng LLM…</p>
          </div>
        ) : activeMode === "md" ? (
          editing ? (
            <div>
              <MdToolbar onFormat={handleFormat} />
              <textarea
                ref={textareaRef}
                data-testid="textarea-markdown"
                value={mdText}
                onChange={(e) => setMdText(e.target.value)}
                aria-label="Nguồn Markdown (md-layout)"
                className="mb-2 mt-2 h-64 w-full rounded-md border border-border bg-surface p-2 font-mono text-sm leading-[1.6] text-text"
              />
              <Button testid="btn-save-layout" onClick={() => void saveLayout()}>
                Lưu
              </Button>
            </div>
          ) : (
            <MarkdownPreview
              markdown={mdText}
              css={savedCss}
              className="h-96 w-full rounded-md border border-border"
            />
          )
        ) : (
          <>
            {docxHtml !== null && (
              <WordEditor
                // Plan M4: Tiptap mount ở word mode (unmount khi switch md → useEditor destroy),
                // css (base + word) scope vào container .word-doc thay vì iframe srcDoc.
                html={docxHtml}
                css={baseCss + wordCss}
                onSave={(html) => void saveWord(html)}
              />
            )}
            <DocStyleTools
              variant="word"
              html={docxHtml}
              initialStyle={job.layout_style}
              onChange={setBaseCss}
              onWordChange={setWordCss}
              onStyleChange={setStyleMap}
            />
            <div className="mt-3 flex justify-end gap-2 border-t border-border pt-3">
              <Button testid="btn-save-style" onClick={() => void saveStyle()}>
                Lưu kiểu trình bày
              </Button>
            </div>
          </>
        )}
      </Card>
    </section>
  );
}
