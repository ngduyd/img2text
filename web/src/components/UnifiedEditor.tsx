import { useQueryClient } from "@tanstack/react-query";
import MDEditor from "@uiw/react-md-editor";
import DOMPurify from "dompurify";
import * as mammoth from "mammoth";
import { splitStyle } from "../lib/splitStyle";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { RefObject } from "react";
import { toast } from "sonner";
import { api } from "../api/client";
import type { Job, LayoutStyle } from "../api/types";
import { buildLayoutStyleCss } from "../lib/docStyle";
import { mapApiError } from "../lib/errors";
import { translate, useT } from "../i18n";
import DocStyleTools from "./DocStyleTools";
import WordEditor from "./editor/WordEditor";
import Button from "./ui/Button";
import Skeleton from "./ui/Skeleton";
import "../styles/editor-surface.css";

export type LayoutMode = "md" | "word";

const FMT: Record<LayoutMode, "md-layout" | "docx-layout"> = {
  md: "md-layout",
  word: "docx-layout",
};

/**
 * Plan M region "Soạn thảo" (gộp card "Tài liệu" + MarkdownEditor cũ; R51:
 * testids preview-docx-frame giữ, tabs preview-md/preview-docx, panel-docs,
 * md-source-preview/md-edit-hint, btn-llm-layout-* gỡ; M5: md mode dùng
 * @uiw/react-md-editor — iframe preview-markdown + MdToolbar/btn-edit-source gỡ).
 *
 * Flow per mode: exportJob(fmt) → downloadExport(fmt) → render. exportJob TỰ
 * gọi LLM khi layout_cache miss, cache-hit trả về nhanh không tốn LLM, nên
 * một đường duy nhất cho cả 2 nhánh. ponytail: nếu sau này cần chặn request
 * khi cache-hit thì mới tách nhánh theo job.layout_cache (lúc đó badge cũng
 * thôi là nguồn sự thật).
 *
 * Mode = prop `mode` (route /jobs/:id/layout/md|word, spec 2026-11-03 AC1–AC3);
 * không còn state — switch-mode-* navigate nên reload/back/forward giữ mode.
 */
export default function UnifiedEditor({
  jobId,
  job,
  markdown,
  editing,
  hostRef,
  mode,
  onActionsChange,
}: {
  jobId: string;
  job: Job;
  markdown: string;
  editing: boolean;
  hostRef?: RefObject<HTMLElement | null>;
  mode: LayoutMode;
  /** Thanh 1 (JobDetail) nhận Save/Preview/badge thay cho hàng điều khiển cũ. */
  onActionsChange?: (
    actions: { mode: LayoutMode; save: () => void; saving: boolean } | null,
  ) => void;
}) {
  const { t } = useT();
  const queryClient = useQueryClient();
  // Plan M3: docx.html cache (PUT html lần trước) → load thẳng, bỏ mammoth/export.
  const docxHtmlCached = job.layout_cache?.docx_html === true;
  // md text = artifact md-layout; markdown prop chỉ là nội dung tạm trước khi artifact về.
  const [mdText, setMdText] = useState(markdown);
  const [docxHtml, setDocxHtml] = useState<string | null>(null);
  const [loaded, setLoaded] = useState({ md: false, word: false });
  const [error, setError] = useState<{ mode: LayoutMode; message: string } | null>(null);  /** Soạn như gdoc: 1 cột giấy ở giữa; preview là TUỲ CHỌN (không chia đôi màn). */
  // Word style: css bắn vào iframe sống, styleMap là bản PUT layout-style.
  const [baseCss, setBaseCss] = useState("");
  const [wordCss, setWordCss] = useState("");
  const [styleMap, setStyleMap] = useState<LayoutStyle | null>(null);

  // layout_style đã lưu → client CSS cho md preview (word iframe tái tạo từ tools hydrate).
  const savedCss = useMemo(() => buildLayoutStyleCss(job.layout_style), [job.layout_style]);
  /*
   * Contract M1: md mode không còn iframe → scope rule `body {…}` xuống preview
   * pane của MDEditor (.w-md-editor-preview), không leak toolbar/trang.
   */
  const mdPaneCss = useMemo(
    () => savedCss.replace(/^body\b/, ".md-pane .w-md-editor-preview"),
    [savedCss],
  );

  const runFlow = useCallback(
    async (m: LayoutMode) => {
      try {
        // Plan M3: word content đã lưu (layout_cache.docx_html) → GET docx.html,
        // không exportJob (không tốn LLM) + không mammoth; 404 → fallback bên dưới.
        const cachedHtml = m === "word" && docxHtmlCached ? await api.getDocxHtml(jobId) : null;
        if (cachedHtml !== null) {
          setDocxHtml(DOMPurify.sanitize(cachedHtml));
        } else {
          if (m === "word") {
            // Cùng nguồn với preview (layout spec) → sửa và xem khớp nhau.
            // mammoth chỉ còn fallback: nó bỏ tab stop/cột/OMML nên nội dung
            // sửa được sẽ khác bản tải về.
            const specHtml = await api.getLayoutPreviewHtml(jobId).catch(() => null);
            if (specHtml !== null && specHtml.trim() !== "") {
              const { css, body } = splitStyle(specHtml);
              setWordCss(css);
              setDocxHtml(DOMPurify.sanitize(body));
              setLoaded((prev) => ({ ...prev, [m]: true }));
              return;
            }
          }
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
   * URL mode = nguồn sự thật duy nhất; JobDetail resolve `mode ?? output_format`
   * nên component này không đoán mode từ job.
   */
  const activeMode: LayoutMode = mode;
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

  const saveLayout = async () => {
    try {
      // Lane I Task 4: Lưu layout → PATCH /layout-content (kind md-layout snapshot).
      await api.patchLayoutContent(jobId, mdText);
      toast.success(translate("editor.saved"));
      // Flag layout_cache đổi phía server → refresh job để badge cập nhật.
      await queryClient.invalidateQueries({ queryKey: ["job", jobId] });
    } catch (err) {
      toast.error(mapApiError(err));
    }
  };

  const saveStyle = async () => {
    try {
      await api.putLayoutStyle(jobId, styleMap);
      toast.success(translate("editor.saved"));
    } catch (err) {
      toast.error(mapApiError(err));
    }
  };

  /** Plan M4: editor.getHTML() (Tiptap) → PUT docx.html → toast + refresh layout_cache. */
  const saveWord = async (html: string) => {
    try {
      await api.putDocxHtml(jobId, html);
      toast.success(translate("editor.saved"));
      // Flag layout_cache.docx_html đổi phía server → refresh job (badge + load sau).
      await queryClient.invalidateQueries({ queryKey: ["job", jobId] });
    } catch (err) {
      toast.error(mapApiError(err));
    }
  };

  /** 2026-11-07: hàng điều khiển riêng đã bỏ — Save/Preview/badge render ở thanh 1 (JobDetail). */
  useEffect(() => {
    if (onActionsChange === undefined) return;
    onActionsChange({
      mode: activeMode,
      save: () => void saveLayoutRef.current(),
      saving: false,
    });
  }, [activeMode, onActionsChange]);

  const saveLayoutRef = useRef(saveLayout);
  saveLayoutRef.current = saveLayout;

  return (
    /* scroll-mt-32: offset qua sticky header job khi btn-edit-doc scroll tới. */
    <section ref={hostRef} data-mode={activeMode} className="scroll-mt-32">
      {/* Màn soạn thảo (route riêng): 1 thanh điều khiển + vùng soạn full chiều cao,
          không bọc trong card nhỏ để editor không bị bóp.
          2026-11-07: switch MD⇄Word dời lên thanh hành động của job (cạnh Download)
          — nút thường, nhãn ghi ĐÍCH; ở đây chỉ còn badge + Save. */}
      <div data-testid="panel-editor" className="flex min-w-0 flex-col gap-3">
        {displayError !== null && (
          <div
            data-testid="layout-error"
            role="alert"
            className="mb-2 flex flex-wrap items-center gap-3 rounded-md border border-error/40 bg-error/10 px-3 py-2 text-error"
          >
            <span className="min-w-0 flex-1 break-words">{displayError}</span>
            <Button
              testid="btn-retry-layout-error"
              variant="secondary"
              size="sm"
              onClick={() => {
                setError(null);
                void runFlow(activeMode);
              }}
            >
              {t("common.retry")}
            </Button>
          </div>
        )}
        <div className="min-w-0">
        {loading ? (
          /* Loading khớp hình content area thật (skeleton, không spinner tròn). */
          <div
            data-testid="layout-loading"
            role="status"
            className="flex flex-col gap-2 rounded-md border border-border bg-surface-2 p-3"
          >
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-96 w-full" />
            <p className="text-sm text-muted">{t("editor.llmRendering")}</p>
          </div>
        ) : activeMode === "md" ? (
          /*
           * Plan M5: MDEditor (uiw) — toolbar built-in + preview split (live)
           * mặc định, luôn show (bỏ toggle btn-edit-source); onChange → mdText.
           * ponytail: preview uiw KHÔNG sanitize HTML thô (rehype-raw) — md chỉ
           * từ artifact VLM/self input cùng origin (self-XSS); upgrade khi cần:
           * previewOptions.rehypePlugins + rehype-sanitize.
           */
          <div
            data-testid="md-editor"
            className="ed-surface md-pane"
            style={
              {
                "--ed-label-source": `"${t("editor.sourcePane")}"`,
                "--ed-label-preview": `"${t("editor.previewPane")}"`,
              } as React.CSSProperties
            }
          >
            <style>{mdPaneCss}</style>
            <MDEditor
              value={mdText}
              // Bỏ nút Preview của app → giữ 1 khung soạn (không mặc định split SOURCE|PREVIEW).
              preview="edit"
              onChange={(v) => setMdText(v ?? "")}
              height="100%"
              hideToolbar={false}
              visibleDragbar={false}
              textareaProps={{ "aria-label": t("editor.textAreaAria") }}
            />
          </div>
        ) : (
          <>
            {docxHtml !== null && (
              <WordEditor
                // Plan M4: Tiptap mount ở word mode (unmount khi switch md → useEditor destroy),
                // css (base + word) scope vào container .word-doc thay vì iframe srcDoc.
                html={docxHtml}
                css={baseCss + wordCss}
                onSave={(html) => void saveWord(html)}
                onSaveStyle={() => void saveStyle()}
                key="word"
                pageTools={
                  <DocStyleTools
                    html={docxHtml}
                    initialStyle={job.layout_style}
                    onChange={setBaseCss}
                    onWordChange={setWordCss}
                    onStyleChange={setStyleMap}
                  />
                }
              />
            )}
          </>
        )}
          </div>
      </div>
    </section>
  );
}
