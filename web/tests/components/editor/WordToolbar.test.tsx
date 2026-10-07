import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import WordToolbar from "../../../src/components/editor/WordToolbar";
import type { WordTableOp } from "../../../src/lib/wordEditor";

/** Plan M3: word toolbar = 1 hàng duy nhất (overflow-x-auto) + emit lệnh selection. */

function renderToolbar(overrides: Partial<Parameters<typeof WordToolbar>[0]> = {}) {
  const onCmd = vi.fn();
  const onSize = vi.fn();
  const onInsertTable = vi.fn();
  const onTableOp = vi.fn();
  render(
    <WordToolbar
      onCmd={onCmd}
      onSize={onSize}
      onInsertTable={onInsertTable}
      onTableOp={onTableOp}
      inTable={false}
      {...overrides}
    />,
  );
  return { onCmd, onSize, onInsertTable, onTableOp };
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
  renderToolbar();
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

it("emit onCmd theo lệnh; font → fontName(arg); size → onSize(pt)", () => {
  const { onCmd, onSize } = renderToolbar();
  fireEvent.click(screen.getByTestId("word-tb-bold"));
  expect(onCmd).toHaveBeenCalledWith("bold");
  fireEvent.click(screen.getByTestId("word-tb-align-justify"));
  expect(onCmd).toHaveBeenCalledWith("justifyFull");
  fireEvent.change(screen.getByTestId("word-tb-font"), { target: { value: "Arial" } });
  expect(onCmd).toHaveBeenCalledWith("fontName", "Arial");
  fireEvent.change(screen.getByTestId("word-tb-size"), { target: { value: "24" } });
  expect(onSize).toHaveBeenCalledWith(24);
  expect(onSize.mock.calls.every((c) => c[0] >= 8 && c[0] <= 72)).toBe(true);
});

it("grid picker 1-10×1-10: mở → click ô → onInsertTable(r, c) → đóng", () => {
  const { onInsertTable } = renderToolbar();
  expect(screen.queryByTestId("word-tb-table-grid")).toBeNull();
  fireEvent.click(screen.getByTestId("word-tb-table"));
  const grid = screen.getByTestId("word-tb-table-grid");
  expect(grid.querySelectorAll("button")).toHaveLength(100);
  fireEvent.click(screen.getByTestId("word-tb-table-2x3"));
  expect(onInsertTable).toHaveBeenCalledWith(2, 3);
  expect(screen.queryByTestId("word-tb-table-grid")).toBeNull();
});

it("caret trong table (inTable): cụm +row −row +col −col hiện và emit đúng op", () => {
  const { onTableOp } = renderToolbar({ inTable: true });
  const ops: [string, WordTableOp][] = [
    ["word-tb-row-add", "row-add"],
    ["word-tb-row-del", "row-del"],
    ["word-tb-col-add", "col-add"],
    ["word-tb-col-del", "col-del"],
  ];
  for (const [testid, op] of ops) {
    fireEvent.click(screen.getByTestId(testid));
    expect(onTableOp).toHaveBeenCalledWith(op);
  }
});

it("caret ngoài table (inTable=false): ẩn cụm row/col", () => {
  renderToolbar({ inTable: false });
  for (const testid of ["word-tb-row-add", "word-tb-row-del", "word-tb-col-add", "word-tb-col-del"]) {
    expect(screen.queryByTestId(testid)).toBeNull();
  }
});
