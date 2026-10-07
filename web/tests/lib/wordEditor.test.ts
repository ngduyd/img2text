import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  applyFontSize,
  caretInTable,
  execWord,
  insertWordTable,
  serializeWordBody,
  wordTableOp,
} from "../../src/lib/wordEditor";

/**
 * Plan M3: doc = document chứa selection. Mọi thao tác phải áp đúng doc đó
 * (VÙN CHỌN), KHÔNG rơi vào document khác / không đụng text ngoài selection.
 * jsdom không có execCommand → spy bằng cách gán doc.execCommand.
 */

let doc: Document;

function selectContents(el: Element): void {
  const range = doc.createRange();
  range.selectNodeContents(el);
  const sel = window.getSelection()!;
  sel.removeAllRanges();
  sel.addRange(range);
}

beforeEach(() => {
  document.body.innerHTML = "";
  doc = document;
});

afterEach(() => {
  Reflect.deleteProperty(document, "execCommand");
});

it("execWord: styleWithCSS=true + lệnh chạy trên ĐÚNG doc truyền vào (chứa selection), không document khác", () => {
  const exec = vi.fn();
  Object.assign(doc, { execCommand: exec });
  const other = document.implementation.createHTMLDocument("other");
  const otherExec = vi.fn();
  Object.assign(other, { execCommand: otherExec });

  execWord(doc, "bold");
  expect(exec).toHaveBeenNthCalledWith(1, "styleWithCSS", false, "true");
  expect(exec).toHaveBeenNthCalledWith(2, "bold", false, undefined);
  execWord(doc, "fontName", "Arial");
  expect(exec).toHaveBeenNthCalledWith(4, "fontName", false, "Arial");

  execWord(other, "italic");
  expect(otherExec).toHaveBeenCalledWith("italic", false, undefined);
  expect(exec).toHaveBeenCalledTimes(4); // doc gốc không nhận thêm lệnh của doc khác
});

it("applyFontSize: wrap span font-size CHỈ quanh selection — text ngoài giữ nguyên", () => {
  doc.body.innerHTML = "<p>abc</p><p>def</p>";
  const [p1, p2] = Array.from(doc.querySelectorAll("p"));
  selectContents(p1);

  applyFontSize(doc, 24);

  const span = p1.querySelector("span");
  expect(span).not.toBeNull();
  expect(span!.style.fontSize).toBe("24pt");
  expect(p1.textContent).toBe("abc");
  // ngoài selection: không bị áp (KHÔNG áp cả document)
  expect(p2.innerHTML).toBe("def");
  expect(doc.querySelectorAll("span")).toHaveLength(1);
});

it("insertWordTable (có execCommand): insertHTML với HTML <table> đúng kích thước", () => {
  const exec = vi.fn();
  Object.assign(doc, { execCommand: exec });

  insertWordTable(doc, 2, 3);

  const call = exec.mock.calls.find((c) => c[0] === "insertHTML");
  expect(call).toBeDefined();
  expect(call![2]).toContain("<table");
  expect((call![2].match(/<td/g) ?? [])).toHaveLength(6);
  expect((call![2].match(/<tr/g) ?? [])).toHaveLength(2);
});

it("insertWordTable (jsdom fallback, không execCommand): bảng thật cắm tại selection", () => {
  doc.body.innerHTML = "<p>x</p>";
  selectContents(doc.querySelector("p")!);

  insertWordTable(doc, 2, 3);

  expect(doc.body.querySelectorAll("table")).toHaveLength(1);
  expect(doc.body.querySelectorAll("tr")).toHaveLength(2);
  expect(doc.body.querySelectorAll("td")).toHaveLength(6);
});

it("wordTableOp: +row −row +col −col theo bảng CHỨA caret; caret ngoài bảng → no-op", () => {
  doc.body.innerHTML =
    '<table><tbody><tr><td>a</td></tr><tr><td>b</td></tr></tbody></table><p>ngoài</p>';
  selectContents(doc.querySelector("td")!);

  wordTableOp(doc, "row-add");
  expect(doc.querySelectorAll("tr")).toHaveLength(3);
  wordTableOp(doc, "col-add");
  expect(doc.querySelectorAll("td")).toHaveLength(6);
  wordTableOp(doc, "col-del");
  expect(doc.querySelectorAll("td")).toHaveLength(3);
  // cell chứa caret đã bị xóa cùng cột → caret rơi vào cell còn lại trong bảng
  selectContents(doc.querySelector("td")!);
  wordTableOp(doc, "row-del");
  expect(doc.querySelectorAll("tr")).toHaveLength(2);

  // caret rời bảng → không áp gì
  selectContents(doc.querySelector("p")!);
  wordTableOp(doc, "row-add");
  expect(doc.querySelectorAll("tr")).toHaveLength(2);
});

it("caretInTable: true khi selection trong td/th, false khi ngoài", () => {
  doc.body.innerHTML = '<table><tbody><tr><td>a</td></tr></tbody></table><p>ngoài</p>';
  selectContents(doc.querySelector("p")!);
  expect(caretInTable(doc)).toBe(false);
  selectContents(doc.querySelector("td")!);
  expect(caretInTable(doc)).toBe(true);
});

it("serializeWordBody: lấy body.innerHTML; không có frame → null", () => {
  expect(serializeWordBody(null)).toBeNull();
  const frame = document.createElement("iframe");
  document.body.appendChild(frame);
  frame.contentDocument!.body.innerHTML = "<p>sửa</p>";
  expect(serializeWordBody(frame)).toBe("<p>sửa</p>");
});
