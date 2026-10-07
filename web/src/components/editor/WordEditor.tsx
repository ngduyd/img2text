import { useEffect, useRef, useState } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";
import type { WordTableOp } from "../../lib/wordEditor";
import {
  applyFontSize,
  caretInTable,
  execWord,
  insertWordTable,
  serializeWordBody,
  wordTableOp,
} from "../../lib/wordEditor";
import Button from "../ui/Button";
import WordToolbar from "./WordToolbar";

/**
 * Plan M3: iframe contentEditable thật cho word mode. srcDoc đã sanitize +
 * style (parent render) — nội dung không chạy script (sandbox chỉ allow
 * same-origin để parent đọc/ghi document). Mọi lệnh từ toolbar bắn vào
 * contentDocument (VÙN CHỌN hiện tại); Lưu serialize body → onSave (PUT docx.html).
 */
export default function WordEditor({
  srcDoc,
  onSave,
}: {
  srcDoc: string;
  onSave: (html: string) => void;
}) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const attachedDoc = useRef<Document | null>(null);
  const trackCaret = useRef<(() => void) | null>(null);
  const [inTable, setInTable] = useState(false);

  // Sau khi srcDoc parse: bật contentEditable + theo dõi caret (in-table → cụm row/col).
  const handleLoad = () => {
    const doc = frameRef.current?.contentDocument ?? null;
    if (!doc?.body) return;
    if (attachedDoc.current && trackCaret.current) {
      attachedDoc.current.removeEventListener("selectionchange", trackCaret.current);
    }
    doc.body.setAttribute("contenteditable", "true");
    const update = () => setInTable(caretInTable(doc));
    doc.addEventListener("selectionchange", update);
    attachedDoc.current = doc;
    trackCaret.current = update;
  };

  useEffect(
    () => () => {
      if (attachedDoc.current && trackCaret.current) {
        attachedDoc.current.removeEventListener("selectionchange", trackCaret.current);
      }
    },
    [],
  );

  const doc = () => frameRef.current?.contentDocument ?? null;
  // Chặn mousedown trên select: blur iframe → mất selection trước khi exec.
  const keepSelection = (e: ReactMouseEvent) => e.preventDefault();

  const save = () => {
    const html = serializeWordBody(frameRef.current);
    if (html !== null) onSave(html);
  };

  return (
    <>
      <WordToolbar
        onCmd={(cmd, arg) => execWord(doc(), cmd, arg)}
        onSize={(pt) => applyFontSize(doc(), pt)}
        onInsertTable={(rows, cols) => insertWordTable(doc(), rows, cols)}
        onTableOp={(op: WordTableOp) => wordTableOp(doc(), op)}
        inTable={inTable}
      />
      <iframe
        ref={frameRef}
        data-testid="preview-docx-frame"
        title="Soạn thảo DOCX"
        // Không allow-scripts: nội dung chỉ chỉnh DOM, không chạy mã; allow-same-origin
        // để parent truy cập contentDocument (execCommand + serialize body).
        sandbox="allow-same-origin"
        srcDoc={srcDoc}
        onLoad={handleLoad}
        className="mt-3 min-h-[60vh] w-full rounded-md border border-border"
      />
      <div className="mt-3 flex justify-end gap-2">
        <Button testid="btn-save-layout-word" onMouseDown={keepSelection} onClick={save}>
          Lưu
        </Button>
      </div>
    </>
  );
}
