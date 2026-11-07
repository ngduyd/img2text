import DOMPurify from "dompurify";
import { EditorContent, useEditor } from "@tiptap/react";
import { useState } from "react";
import type { ReactNode } from "react";
import { scopeWordPaneCss } from "../../lib/docStyle";
import { useT } from "../../i18n";
import { wordExtensions } from "../../lib/wordEditor";
import Button from "../ui/Button";
import WordToolbar from "./WordToolbar";
import type { Dock } from "./WordToolbar";

/** Chiều cao vùng soạn (khớp iframe min-h-[60vh] của M3, trừ padding). */
const PANE_CSS = ".word-doc .ProseMirror { min-height: 55vh; }";

const DOCK_KEY = "editor.toolbarDock";
const DOCKS: Dock[] = ["top", "bottom", "left", "right"];

function readDock(): Dock {
  const saved = typeof localStorage === "undefined" ? null : localStorage.getItem(DOCK_KEY);
  return DOCKS.includes(saved as Dock) ? (saved as Dock) : "top";
}

/**
 * Plan M4: iframe contentEditable (M3) → editor Tiptap. Component chỉ mount khi
 * mode word + đã load docxHtml → switch sang md là unmount, useEditor tự destroy
 * (không leak listener/selectionchange). Lưu = editor.getHTML() → onSave (PUT docx.html).
 *
 * 2026-11-07: toolbar dock 4 phía (nhớ qua localStorage), dính sát vùng page —
 * tờ giấy tự cuộn BÊN TRONG `.wp-paper-scroll`, không để document ngoài cuộn.
 */
export default function WordEditor({
  html,
  css,
  onSave,
  onSaveStyle,
  pageTools,
}: {
  html: string;
  css: string;
  onSave: (html: string) => void;
  /** Lưu kiểu trang (layout-style) — gom về cùng 1 chỗ với Save nội dung kiểu gdoc. */
  onSaveStyle?: () => void;
  /** Page & text style (DocStyleTools) — bơm vào popover "Trang" của toolbar. */
  pageTools?: ReactNode;
}) {
  const { t } = useT();
  const [dock, setDock] = useState<Dock>(readDock);
  const editor = useEditor({
    extensions: wordExtensions,
    // Ranh giới nạp: sanitize lần nữa trước khi vào nội dung soạn (runFlow đã sanitize lúc load).
    content: DOMPurify.sanitize(html),
  });

  const changeDock = (d: Dock) => {
    setDock(d);
    try {
      localStorage.setItem(DOCK_KEY, d);
    } catch {
      // localStorage bị chặn → chỉ mất lựa chọn ở lần mở sau.
    }
  };

  return (
    <>
      <style>{`${PANE_CSS}${scopeWordPaneCss(css)}`}</style>
      {/* Soạn kiểu Google Docs: 1 tờ giấy A4 ở giữa, không chia đôi màn.
          Bản xem trang A4 thật (paged.js) gấp lại trong "Xem trang A4". */}
      <div data-testid="ed-work" data-dock={dock} className="ed-work">
        <WordToolbar
          editor={editor}
          dock={dock}
          onDockChange={changeDock}
          pageTools={pageTools}
        />
        <div className="wp-paper-scroll">
          {/* preview-docx-frame giữ testid (e2e M4) — giờ là container editor, không còn iframe. */}
          <div data-testid="preview-docx-frame" className="word-doc wp-paper">
            <EditorContent editor={editor} />
          </div>
        </div>
      </div>
      <div className="mt-3 flex items-center justify-end gap-2">
        <div className="flex shrink-0 items-center gap-2">
          {onSaveStyle && (
            <Button testid="btn-save-style" variant="secondary" onClick={onSaveStyle}>
              {t("common.saveLayout")}
            </Button>
          )}
          <Button testid="btn-save-layout-word" onClick={() => editor && onSave(editor.getHTML())}>
            {t("editor.saveContent")}
          </Button>
        </div>
      </div>
    </>
  );
}
