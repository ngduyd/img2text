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
      {/* D7/D8: soạn | xem trước A4 song song (≥lg), xếp dọc dưới lg. */}
      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        {/* preview-docx-frame giữ testid (e2e M4) — giờ là container editor, không còn iframe. */}
        <div
          data-testid="preview-docx-frame"
          className="word-doc min-h-[60vh] w-full rounded-md border border-border p-3"
        >
          <EditorContent editor={editor} />
        </div>
        <PagePreview html={docHtml} css={css} />
      </div>
      <div className="mt-3 flex justify-end gap-2">
        <Button testid="btn-save-layout-word" onClick={() => editor && onSave(editor.getHTML())}>
          {t("common.save")}
        </Button>
      </div>
    </>
  );
}
