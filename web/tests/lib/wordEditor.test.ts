/**
 * Plan M4: test roundtrip HTML subset word → Tiptap → getHTML() — output phải
 * còn nguyên cho html_to_docx của server (span font-size/font-family, align,
 * list, table). Chạy trên instance @tiptap/core thật (jsdom), không qua React.
 */
import { Editor } from "@tiptap/core";
import { expect, it } from "vitest";
import { scopeWordPaneCss } from "../../src/lib/docStyle";
import { WORD_SIZES, wordExtensions } from "../../src/lib/wordEditor";

function makeEditor(content: string): Editor {
  return new Editor({ element: document.createElement("div"), extensions: wordExtensions, content });
}

it("roundtrip getHTML: span font-size/font-family + text-align + ul + table còn nguyên", () => {
  const editor = makeEditor(
    '<p style="text-align: center"><span style="font-family: Arial; font-size: 16pt">Chữ</span></p>' +
      "<ul><li>Một</li></ul>" +
      "<table><tbody><tr><td>A</td></tr></tbody></table>",
  );
  const html = editor.getHTML();
  expect(html).toContain("text-align: center");
  expect(html).toContain("font-size: 16pt");
  expect(html).toContain("font-family: Arial");
  expect(html).toContain("<ul>");
  expect(html).toContain("<table");
  editor.destroy();
});

it("setMark fontSize áp THEO VÙN CHỌN: chỉ selection đổi, còn lại nguyên", () => {
  const editor = makeEditor("<p>X Y Z</p>");
  editor.commands.setTextSelection({ from: 3, to: 4 });
  editor.commands.setMark("textStyle", { fontSize: "16pt" });
  const html = editor.getHTML();
  expect(html).toMatch(/<p>X <span[^>]*font-size: 16pt[^>]*>Y<\/span> Z<\/p>/);
  editor.destroy();
});

it("toggleBold áp THEO VÙN CHỌN: chỉ selection thành <strong>", () => {
  const editor = makeEditor("<p>X Y Z</p>");
  editor.commands.setTextSelection({ from: 3, to: 4 });
  editor.commands.toggleBold();
  expect(editor.getHTML()).toBe("<p>X <strong>Y</strong> Z</p>");
  expect(editor.isActive("bold")).toBe(true);
  editor.destroy();
});

it("setTextAlign + insertTable ra markup html_to_docx parse được", () => {
  const editor = makeEditor("<p>Chào</p>");
  editor.commands.setTextAlign("center");
  editor.commands.insertTable({ rows: 2, cols: 3, withHeaderRow: true });
  const html = editor.getHTML();
  expect(html).toContain("text-align: center");
  expect(html).toContain("<table");
  expect(html).toContain("<th");
  editor.destroy();
});

it("WORD_SIZES phủ đúng dải 8-72 pt", () => {
  expect(WORD_SIZES[0]).toBe(8);
  expect(WORD_SIZES[WORD_SIZES.length - 1]).toBe(72);
});

it("scopeWordPaneCss: body → & dưới .word-doc (CSS nesting), rỗng → rỗng", () => {
  expect(scopeWordPaneCss("")).toBe("");
  expect(scopeWordPaneCss("body { font-size: 16px; }")).toBe(
    ".word-doc { & { font-size: 16px; } }",
  );
});
