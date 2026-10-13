import DOMPurify from "dompurify";
import { EditorContent, useEditor } from "@tiptap/react";
import { scopeWordPaneCss } from "../../lib/docStyle";
import { wordExtensions } from "../../lib/wordEditor";
import Button from "../ui/Button";
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
  const editor = useEditor({
    extensions: wordExtensions,
    // Ranh giới nạp: sanitize lần nữa trước khi vào nội dung soạn (runFlow đã sanitize lúc load).
    content: DOMPurify.sanitize(html),
  });

  return (
    <>
      <WordToolbar editor={editor} />
      <style>{`${PANE_CSS}${scopeWordPaneCss(css)}`}</style>
      {/* preview-docx-frame giữ testid (e2e M4) — giờ là container editor, không còn iframe. */}
      <div
        data-testid="preview-docx-frame"
        className="word-doc mt-3 min-h-[60vh] w-full rounded-md border border-border p-3"
      >
        <EditorContent editor={editor} />
      </div>
      <div className="mt-3 flex justify-end gap-2">
        <Button testid="btn-save-layout-word" onClick={() => editor && onSave(editor.getHTML())}>
          Lưu
        </Button>
      </div>
    </>
  );
}
