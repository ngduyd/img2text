import { useQueryClient } from "@tanstack/react-query";
import MDEditor from "@uiw/react-md-editor";
import DOMPurify from "dompurify";
import * as mammoth from "mammoth";
import { RefreshCw, Sparkles } from "lucide-react";
import type { Editor } from "@tiptap/core";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { RefObject } from "react";
import { toast } from "sonner";
import { api } from "../api/client";
import type { Job, LayoutStyle, Suggestion } from "../api/types";
import { buildLayoutStyleCss } from "../lib/docStyle";
import { mapApiError } from "../lib/errors";
import DocStyleTools from "./DocStyleTools";
import SuggestionsPanel from "./SuggestionsPanel";
import WordEditor from "./editor/WordEditor";
import Badge from "./ui/Badge";
import Button from "./ui/Button";
import Card from "./ui/Card";
import Skeleton from "./ui/Skeleton";

type Mode = "md" | "word";

const FMT: Record<Mode, "md-layout" | "docx-layout"> = { md: "md-layout", word: "docx-layout" };

/** Fuzzy find: whitespace-normalized match of needle in haystack → raw [start, end). */
function findFuzzy(haystack: string, needle: string): [number, number] | null {
  const n = needle.replace(/\s+/g, " ").trim();
  if (!n) return null;
  for (let i = 0; i < haystack.length; i++) {
    let hi = i;
    let ni = 0;
    let ok = true;
    while (ni < n.length) {
      while (hi < haystack.length && /\s/.test(haystack[hi])) hi++;
      if (hi >= haystack.length || haystack[hi] !== n[ni]) {
        ok = false;
        break;
      }
      hi++;
      ni++;
    }
    if (ok) {
      let end = hi;
      while (end > i && /\s/.test(haystack[end - 1])) end--;
      return [i, end];
    }
  }
  return null;
}

/** Find phrase within a single Tiptap text node → PM positions. */
function findPhraseInEditor(
  editor: Editor,
  phrase: string,
): { from: number; to: number } | null {
  const doc = editor.state.doc;
  let result: { from: number; to: number } | null = null;
  doc.descendants((node, pos) => {
    if (result) return false;
    if (node.isText && node.text) {
      const found = findFuzzy(node.text, phrase);
      if (found) {
        result = { from: pos + 1 + found[0], to: pos + 1 + found[1] };
        return false;
      }
    }
  });
  return result;
}

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
  // Word style: css bắn vào iframe sống, styleMap là bản PUT layout-style.
  const [baseCss, setBaseCss] = useState("");
  const [wordCss, setWordCss] = useState("");
  const [styleMap, setStyleMap] = useState<LayoutStyle | null>(null);

  // Plan proofread: suggestions + panel toggle + Tiptap editor ref (word mode).
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [panelOpen, setPanelOpen] = useState(false);
  const [proofreadLoading, setProofreadLoading] = useState(false);
  const wordEditorRef = useRef<Editor | null>(null);
  const pendingCount = suggestions.filter((s) => s.status === "pending").length;

  useEffect(() => {
    api.getSuggestions(jobId).then(setSuggestions).catch(() => {});
  }, [jobId]);

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

  /** Plan proofread: jump tới vị trí original trong editor (MD textarea / Tiptap). */
  const handleJump = (s: Suggestion) => {
    if (activeMode === "md") {
      const ta = hostRef?.current?.querySelector<HTMLTextAreaElement>(
        ".w-md-editor-text-input, textarea",
      );
      if (!ta) return;
      const found = findFuzzy(ta.value, s.original);
      if (!found) {
        toast.error("Không tìm thấy trong nội dung");
        return;
      }
      ta.focus();
      ta.setSelectionRange(found[0], found[1]);
      ta.scrollIntoView({ behavior: "smooth", block: "center" });
    } else {
      const editor = wordEditorRef.current;
      if (!editor) return;
      const found = findPhraseInEditor(editor, s.original);
      if (!found) {
        toast.error("Không tìm thấy trong nội dung");
        return;
      }
      editor.chain().focus().setTextSelection({ from: found.from, to: found.to }).scrollIntoView().run();
    }
  };

  /** Plan proofread: replace original → suggestion trong editor → save → accept. */
  const handleAccept = async (sid: number) => {
    const s = suggestions.find((x) => x.id === sid);
    if (!s) return;
    try {
      if (activeMode === "md") {
        const ta = hostRef?.current?.querySelector<HTMLTextAreaElement>(
          ".w-md-editor-text-input, textarea",
        );
        if (!ta) throw new Error("no textarea");
        const found = findFuzzy(ta.value, s.original);
        if (!found) {
          toast.error("Không tìm thấy trong nội dung");
          return;
        }
        const newText = ta.value.slice(0, found[0]) + s.suggestion + ta.value.slice(found[1]);
        setMdText(newText);
        await api.putMdLayoutContent(jobId, newText);
      } else {
        const editor = wordEditorRef.current;
        if (!editor) throw new Error("no editor");
        const found = findPhraseInEditor(editor, s.original);
        if (!found) {
          toast.error("Không tìm thấy trong nội dung");
          return;
        }
        editor.chain().focus().insertContentAt({ from: found.from, to: found.to }, s.suggestion).run();
        await api.putDocxHtml(jobId, editor.getHTML());
      }
      await api.acceptSuggestion(jobId, sid);
      setSuggestions((prev) => prev.filter((x) => x.id !== sid));
      toast.success("Đã áp dụng gợi ý.");
    } catch (err) {
      toast.error(mapApiError(err));
    }
  };

  /** Plan proofread: reject → remove khỏi list. */
  const handleReject = async (sid: number) => {
    try {
      await api.rejectSuggestion(jobId, sid);
      setSuggestions((prev) => prev.filter((x) => x.id !== sid));
    } catch (err) {
      toast.error(mapApiError(err));
    }
  };

  /** Plan proofread: chạy lại proofread thủ công (nút refresh). */
  const handleRefresh = async () => {
    setProofreadLoading(true);
    try {
      const { count } = await api.runProofread(jobId);
      toast.success(`Đã tìm thấy ${count} gợi ý.`);
      const items = await api.getSuggestions(jobId);
      setSuggestions(items);
      setPanelOpen(true);
    } catch (err) {
      toast.error(mapApiError(err));
    } finally {
      setProofreadLoading(false);
    }
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
            <Button
              testid="btn-refresh-proofread"
              variant="ghost"
              size="sm"
              title="Chạy lại kiểm tra"
              aria-label="Chạy lại kiểm tra"
              disabled={proofreadLoading}
              onClick={() => void handleRefresh()}
            >
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
            </Button>
            <Button
              testid="btn-proofread"
              variant="secondary"
              aria-pressed={panelOpen}
              onClick={() => setPanelOpen((o) => !o)}
            >
              <Sparkles className="h-4 w-4" aria-hidden="true" />
              Kiểm tra lỗi
              {pendingCount > 0 && (
                <span
                  data-testid="proofread-badge"
                  className="ml-1 rounded-full bg-error px-1.5 text-xs font-semibold text-white"
                >
                  {pendingCount}
                </span>
              )}
            </Button>
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
        <div className="flex gap-4">
          <div className="min-w-0 flex-1">
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
          /*
           * Plan M5: MDEditor (uiw) — toolbar built-in + preview split (live)
           * mặc định, luôn show (bỏ toggle btn-edit-source); onChange → mdText.
           * ponytail: preview uiw KHÔNG sanitize HTML thô (rehype-raw) — md chỉ
           * từ artifact VLM/self input cùng origin (self-XSS); upgrade khi cần:
           * previewOptions.rehypePlugins + rehype-sanitize.
           */
          <div data-testid="md-editor" className="md-pane">
            <style>{mdPaneCss}</style>
            <MDEditor value={mdText} onChange={(v) => setMdText(v ?? "")} height="24rem" />
            <div className="mt-3 flex justify-end border-t border-border pt-3">
              <Button testid="btn-save-layout" onClick={() => void saveLayout()}>
                Lưu
              </Button>
            </div>
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
                editorRef={wordEditorRef}
              />
            )}
            <DocStyleTools
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
          </div>
          {panelOpen && (
            <aside className="w-72 shrink-0">
              <SuggestionsPanel
                suggestions={suggestions}
                onAccept={(sid) => void handleAccept(sid)}
                onReject={(sid) => void handleReject(sid)}
                onJump={handleJump}
              />
            </aside>
          )}
        </div>
      </Card>
    </section>
  );
}
