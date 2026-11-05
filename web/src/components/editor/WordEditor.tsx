import DOMPurify from "dompurify";
import { EditorContent, useEditor } from "@tiptap/react";
import { useState } from "react";
import { scopeWordPaneCss } from "../../lib/docStyle";
import { useT } from "../../i18n";
import { wordExtensions } from "../../lib/wordEditor";
import Button from "../ui/Button";
import PagePreview from "./PagePreview";
import WordToolbar from "./WordToolbar";

/** Chiều cao vùng soạn (khớp iframe min-h-[60vh] của M3, trừ padding). */
const PANE_CSS = ".word-doc .ProseMirror { min-height: 55vh; }";

/**
 * Plan M4: iframe contentEditable (M3) → editor Tiptap. Component chỉ mount khi
 * mode word + đã load docxHtml → switch sang md là unmount, useEditor tự destroy
 * (không leak listener/selectionchange). Lưu = editor.getHTML() → onSave (PUT docx.html).
 */
export default function WordEditor({
  html,
  css,
  onSave,
}: {
  html: string;
  css: string;
  onSave: (html: string) => void;
}) {
  const { t } = useT();
  // D7: bản HTML mới nhất đẩy sang PagePreview (debounce nằm trong component đó).
  const [docHtml, setDocHtml] = useState(html);
  const editor = useEditor({
    extensions: wordExtensions,
    // Ranh giới nạp: sanitize lần nữa trước khi vào nội dung soạn (runFlow đã sanitize lúc load).
    content: DOMPurify.sanitize(html),
    onUpdate: ({ editor: e }) => setDocHtml(e.getHTML()),
  });

  return (
    <>
      <WordToolbar editor={editor} />
      <style>{`${PANE_CSS}${scopeWordPaneCss(css)}`}</style>
      {/* Soạn kiểu Google Docs: 1 tờ giấy A4 ở giữa, không chia đôi màn.
          Bản xem trang A4 thật (paged.js) gấp lại trong "Xem trang A4". */}
      <div className="wp-paper-scroll">
        {/* preview-docx-frame giữ testid (e2e M4) — giờ là container editor, không còn iframe. */}
        <div data-testid="preview-docx-frame" className="word-doc wp-paper">
          <EditorContent editor={editor} />
        </div>
      </div>
      <details className="mt-3 rounded-md border border-border bg-surface">
        <summary
          data-testid="btn-toggle-page-preview"
          className="cursor-pointer list-none px-3 py-2 text-sm text-muted [&::-webkit-details-marker]:hidden"
        >
          {t("editor.pagePreview")}
        </summary>
        <div className="border-t border-border p-3">
          <PagePreview html={docHtml} css={css} />
        </div>
      </details>
      <div className="mt-3 flex justify-end gap-2">
        <Button testid="btn-save-layout-word" onClick={() => editor && onSave(editor.getHTML())}>
          {t("common.save")}
        </Button>
      </div>
    </>
  );
}
