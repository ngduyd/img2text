import { fireEvent, render, screen } from "@testing-library/react";
import { Editor } from "@tiptap/core";
import { expect, it } from "vitest";
import WordToolbar from "../../../src/components/editor/WordToolbar";
import { wordExtensions } from "../../../src/lib/wordEditor";

/**
 * Plan M4: toolbar giữ testid word-tb-* + layout 1 hàng của M3, nhưng lệnh chạy
 * trên instance Tiptap thật (jsdom) — assert qua editor.isActive/getHTML thay vì
 * mock callback execCommand.
 */

function makeEditor(content = "<p>Chào thế giới</p>"): Editor {
  return new Editor({ element: document.createElement("div"), extensions: wordExtensions, content });
}

function renderToolbar(editor: Editor | null) {
  return render(<WordToolbar editor={editor} />);
}

const COMMAND_IDS = [
  "word-tb-undo",
  "word-tb-redo",
  "word-tb-bold",
  "word-tb-italic",
  "word-tb-underline",
  "word-tb-align-left",
  "word-tb-align-center",
  "word-tb-align-right",
  "word-tb-align-justify",
  "word-tb-list-ul",
  "word-tb-list-ol",
  "word-tb-clear",
];

it("1 container role=toolbar duy nhất: 1 hàng (overflow-x-auto, gap-2, không flex-wrap) + đủ testid", () => {
  renderToolbar(makeEditor());
  const root = screen.getByTestId("word-toolbar");
  const rows = root.querySelectorAll('[role="toolbar"]');
  expect(rows).toHaveLength(1);
  expect(rows[0]).toHaveClass("overflow-x-auto");
  expect(rows[0]).toHaveClass("gap-2");
  expect(rows[0]).not.toHaveClass("flex-wrap");
  for (const id of [...COMMAND_IDS, "word-tb-font", "word-tb-size", "word-tb-table"]) {
    expect(screen.getByTestId(id)).toBeInTheDocument();
  }
  // label screen-reader/title (a11y)
  for (const id of COMMAND_IDS) {
    expect(screen.getByTestId(id)).toHaveAttribute("title");
    expect(screen.getByTestId(id)).toHaveAttribute("aria-label");
  }
});

it("bold áp THEO VÙN CHỌN: chỉ selection đổi <strong> + aria-pressed theo editor", () => {
  const editor = makeEditor();
  editor.commands.setTextSelection({ from: 1, to: 5 });
  renderToolbar(editor);
  fireEvent.click(screen.getByTestId("word-tb-bold"));
  expect(editor.isActive("bold")).toBe(true);
  expect(editor.getHTML()).toBe("<p><strong>Chào</strong> thế giới</p>");
  expect(screen.getByTestId("word-tb-bold")).toHaveAttribute("aria-pressed", "true");
});

it("clear gỡ định dạng; undo/redo đi theo history của editor", () => {
  const editor = makeEditor();
  editor.commands.setTextSelection({ from: 1, to: 5 });
  renderToolbar(editor);
  fireEvent.click(screen.getByTestId("word-tb-bold"));
  expect(editor.getHTML()).toContain("<strong>");
  fireEvent.click(screen.getByTestId("word-tb-clear"));
  expect(editor.getHTML()).not.toContain("<strong>");
  fireEvent.click(screen.getByTestId("word-tb-undo"));
  expect(editor.getHTML()).toContain("<strong>");
  fireEvent.click(screen.getByTestId("word-tb-redo"));
  expect(editor.getHTML()).not.toContain("<strong>");
});

it("font → textStyle fontFamily; size (8-72pt) → fontSize, merge attrs trên selection", () => {
  const editor = makeEditor();
  editor.commands.setTextSelection({ from: 1, to: 5 });
  renderToolbar(editor);
  fireEvent.change(screen.getByTestId("word-tb-font"), { target: { value: "Arial" } });
  fireEvent.change(screen.getByTestId("word-tb-size"), { target: { value: "24" } });
  const html = editor.getHTML();
  expect(html).toContain("font-family: Arial");
  expect(html).toContain("font-size: 24pt");
  // dải 8-72pt giữ nguyên (placeholder rỗng = chưa chọn)
  const sizes = Array.from((screen.getByTestId("word-tb-size") as HTMLSelectElement).options).map(
    (o) => o.value,
  );
  expect(sizes[0]).toBe("");
  expect(sizes[1]).toBe("8");
  expect(sizes[sizes.length - 1]).toBe("72");
});

it("align → setTextAlign trên block; aria-pressed theo trạng thái editor", () => {
  const editor = makeEditor();
  renderToolbar(editor);
  fireEvent.click(screen.getByTestId("word-tb-align-center"));
  expect(editor.isActive({ textAlign: "center" })).toBe(true);
  expect(editor.getHTML()).toContain("text-align: center");
  expect(screen.getByTestId("word-tb-align-center")).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByTestId("word-tb-align-justify"));
  expect(editor.isActive({ textAlign: "justify" })).toBe(true);
  expect(screen.getByTestId("word-tb-align-justify")).toHaveAttribute("aria-pressed", "true");
});

it("list ul/ol → toggleBulletList/toggleOrderedList", () => {
  const editor = makeEditor();
  renderToolbar(editor);
  fireEvent.click(screen.getByTestId("word-tb-list-ul"));
  expect(editor.isActive("bulletList")).toBe(true);
  expect(editor.getHTML()).toContain("<ul>");
  fireEvent.click(screen.getByTestId("word-tb-list-ol"));
  expect(editor.isActive("orderedList")).toBe(true);
  expect(editor.isActive("bulletList")).toBe(false);
});

it("grid picker 1-10×1-10: mở → click ô → insertTable với header row → đóng", () => {
  const editor = makeEditor();
  renderToolbar(editor);
  expect(screen.queryByTestId("word-tb-table-grid")).toBeNull();
  fireEvent.click(screen.getByTestId("word-tb-table"));
  const grid = screen.getByTestId("word-tb-table-grid");
  expect(grid.querySelectorAll("button")).toHaveLength(100);
  fireEvent.click(screen.getByTestId("word-tb-table-2x3"));
  expect(editor.isActive("table")).toBe(true);
  expect(editor.getHTML()).toMatch(/<table/);
  expect(editor.getHTML().match(/<tr/g)).toHaveLength(2); // rows:2 + withHeaderRow
  expect(editor.getHTML()).toContain("<th");
  expect(screen.queryByTestId("word-tb-table-grid")).toBeNull();
});

it("caret trong table: cụm +row −row +col −col hiện và sửa bảng thật", () => {
  const editor = makeEditor("<p>x</p>");
  editor.commands.insertTable({ rows: 2, cols: 3, withHeaderRow: false });
  renderToolbar(editor);
  expect(editor.isActive("table")).toBe(true);
  expect(screen.getByTestId("word-tb-row-add")).toBeInTheDocument();
  // Nhóm 3: table row/col tách sang hàng thứ 2 — không còn trong strip overflow-x-auto.
  expect(screen.getByRole("toolbar")).not.toContainElement(screen.getByTestId("word-tb-row-add"));
  expect(screen.getByTestId("word-tb-table-controls")).toContainElement(
    screen.getByTestId("word-tb-row-add"),
  );
  const count = (tag: string) => editor.getHTML().match(new RegExp(`<${tag}`, "g"))?.length ?? 0;
  expect(count("tr")).toBe(2);
  fireEvent.click(screen.getByTestId("word-tb-row-add"));
  expect(count("tr")).toBe(3);
  fireEvent.click(screen.getByTestId("word-tb-row-del"));
  expect(count("tr")).toBe(2);
  fireEvent.click(screen.getByTestId("word-tb-col-add"));
  expect(count("td")).toBe(8);
  fireEvent.click(screen.getByTestId("word-tb-col-del"));
  expect(count("td")).toBe(6);
});

it("caret ngoài table (không có table): ẩn cụm row/col", () => {
  renderToolbar(makeEditor());
  for (const testid of ["word-tb-row-add", "word-tb-row-del", "word-tb-col-add", "word-tb-col-del"]) {
    expect(screen.queryByTestId(testid)).toBeNull();
  }
});
