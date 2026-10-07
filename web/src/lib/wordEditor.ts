/**
 * Plan M3 word editing — mọi thao tác nhận `doc` = contentDocument của iframe
 * soạn thảo và áp lên VÙN CHỌN của doc đó (selection/anchorNode), KHÔNG bao giờ
 * áp cả document chính. execCommand (deprecated nhưng chuẩn của contentEditable)
 * luôn chạy với styleWithCSS=true để ra span style; cỡ chữ tuỳ ý wrap span thủ
 * công vì execCommand fontSize chỉ nhận giá trị 1-7.
 */

export type WordTableOp = "row-add" | "row-del" | "col-add" | "col-del";

function selectionOf(doc: Document | null): Selection | null {
  if (!doc) return null;
  const win = doc.defaultView;
  if (win && typeof win.getSelection === "function") return win.getSelection();
  return typeof doc.getSelection === "function" ? doc.getSelection() : null;
}

/** Element chứa caret/selection (anchorNode có thể là text node). */
function anchorElement(doc: Document | null): Element | null {
  const node = selectionOf(doc)?.anchorNode ?? null;
  if (!node) return null;
  return node.nodeType === 1 ? (node as Element) : node.parentElement;
}

/** Chạy 1 lệnh định dạng trên selection của `doc` (styleWithCSS → span style). */
export function execWord(doc: Document | null, cmd: string, arg?: string): void {
  if (!doc || typeof doc.execCommand !== "function") return;
  doc.execCommand("styleWithCSS", false, "true");
  doc.execCommand(cmd, false, arg ?? undefined);
}

/** Cỡ chữ tùy ý (pt): wrap VÙN CHỌN trong span style font-size — không đụng text ngoài selection. */
export function applyFontSize(doc: Document | null, pt: number): void {
  const sel = selectionOf(doc);
  if (!doc || !sel || sel.rangeCount === 0) return;
  const range = sel.getRangeAt(0);
  const span = doc.createElement("span");
  span.style.fontSize = `${pt}pt`;
  span.appendChild(range.extractContents());
  range.insertNode(span);
  sel.removeAllRanges();
  const inner = doc.createRange();
  inner.selectNodeContents(span);
  sel.addRange(inner);
}

function tableHtml(rows: number, cols: number): string {
  const cell = '<td style="border: 1px solid #8b949e; padding: 2px 6px;"></td>';
  const tr = `<tr>${cell.repeat(cols)}</tr>`;
  return `<table style="border-collapse: collapse;">${tr.repeat(rows)}</table>`;
}

/** Chèn bảng tại caret (grid picker 1-10 × 1-10) qua execCommand insertHTML. */
export function insertWordTable(doc: Document | null, rows: number, cols: number): void {
  if (!doc) return;
  const html = tableHtml(rows, cols);
  if (typeof doc.execCommand === "function") {
    doc.execCommand("insertHTML", false, html);
    return;
  }
  // Fallback (jsdom không có execCommand): cắm cùng HTML vào range tại caret.
  const sel = selectionOf(doc);
  if (!sel || sel.rangeCount === 0) return;
  const range = sel.getRangeAt(0);
  range.deleteContents();
  const holder = doc.createElement("div");
  holder.innerHTML = html;
  const table = holder.firstElementChild;
  if (!table) return;
  range.insertNode(table);
  range.setStartAfter(table);
  range.collapse(true);
  sel.removeAllRanges();
  sel.addRange(range);
}

/** Cụm +row −row +col −col: áp lên bảng CHỨA caret (không có caret trong bảng → no-op). */
export function wordTableOp(doc: Document | null, op: WordTableOp): void {
  const cell = anchorElement(doc)?.closest("td, th") as HTMLTableCellElement | null;
  const row = cell?.parentElement as HTMLTableRowElement | null;
  const table = cell?.closest("table") as HTMLTableElement | null;
  if (!doc || !cell || !row || !table) return;
  const index = cell.cellIndex;
  if (op === "row-add") {
    const tr = doc.createElement("tr");
    for (let i = 0; i < row.cells.length; i += 1) tr.appendChild(doc.createElement("td"));
    row.after(tr);
  } else if (op === "row-del") {
    row.remove();
  } else if (op === "col-add") {
    for (const r of table.rows) {
      const td = doc.createElement("td");
      const ref = r.cells[index + 1] ?? null;
      if (ref) r.insertBefore(td, ref);
      else r.appendChild(td);
    }
  } else {
    for (const r of table.rows) r.cells[index]?.remove();
  }
}

/** Caret có nằm trong bảng không → bật/tắt cụm +row/−row/+col/−col trên toolbar. */
export function caretInTable(doc: Document | null): boolean {
  const el = anchorElement(doc);
  return el !== null && el.closest("table") !== null;
}

/** Serialize iframe body (nội dung soạn thảo) — head/style không lưu; không đọc được → null. */
export function serializeWordBody(frame: HTMLIFrameElement | null): string | null {
  const body = frame?.contentDocument?.body ?? null;
  return body ? body.innerHTML : null;
}
