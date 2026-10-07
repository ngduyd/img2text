import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as mammoth from "mammoth";
import WordTool from "../../src/pages/WordTool";

vi.mock("mammoth", () => ({ convertToHtml: vi.fn() }));

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function uploadDocx(value: string) {
  vi.mocked(mammoth.convertToHtml).mockResolvedValue({ value, messages: [] } as never);
  render(<WordTool />);
  const file = new File(["PK"], "van-ban.docx", {
    type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  });
  await userEvent.upload(screen.getByTestId("input-word-file"), file);
  await screen.findByTestId("word-preview");
}

function srcdoc(): string {
  return screen.getByTestId("word-preview").getAttribute("srcdoc") ?? "";
}

it("renders word-tool: upload, preview + tools panel, empty state; no URL loader, no export controls", () => {
  render(<WordTool />);
  expect(screen.getByTestId("word-tool")).toBeInTheDocument();
  expect(screen.getByTestId("word-upload")).toBeInTheDocument();
  expect(screen.getByTestId("word-tools")).toBeInTheDocument();
  expect(screen.getByText("Chưa có tài liệu")).toBeInTheDocument();
  // URL loader removed per user instruction (R51 exception)
  expect(screen.queryByTestId("select-export-format")).not.toBeInTheDocument();
  expect(screen.queryByTestId("btn-word-export")).not.toBeInTheDocument();
  expect(screen.queryByTestId("btn-word-to-md")).not.toBeInTheDocument();
  expect(screen.queryByTestId("input-word-url")).not.toBeInTheDocument();
  expect(screen.queryByTestId("btn-word-load")).not.toBeInTheDocument();
  expect(screen.queryByTestId("word-url-error")).not.toBeInTheDocument();
});

it("upload docx → mammoth → sanitized iframe srcdoc with single style block", async () => {
  await uploadDocx("<h1>Chào</h1><script>alert(1)</script>");
  expect(mammoth.convertToHtml).toHaveBeenCalledTimes(1);
  const doc = srcdoc();
  expect(screen.getByTestId("word-preview")).toHaveAttribute("sandbox", "");
  expect(doc).toContain("Chào");
  expect(doc).not.toContain("script");
  expect(doc).toContain('<style id="word-style">');
});

it("font family + size change → style block family/size rule changes", async () => {
  await uploadDocx("<h1>A</h1>");
  expect(srcdoc()).toContain('font-family: "system-ui"');
  await userEvent.selectOptions(screen.getByTestId("tool-font-family"), "Arial");
  expect(srcdoc()).toContain('font-family: "Arial"');
  fireEvent.change(screen.getByTestId("tool-font-size"), { target: { value: "24" } });
  expect(srcdoc()).toContain("font-size: 24px");
});

it("margins → body padding rule changes", async () => {
  await uploadDocx("<h1>A</h1>");
  expect(srcdoc()).toContain("padding-left: 2.5cm");
  expect(srcdoc()).toContain("padding-right: 2.5cm");
  fireEvent.change(screen.getByTestId("tool-margin-left"), { target: { value: "4" } });
  fireEvent.change(screen.getByTestId("tool-margin-right"), { target: { value: "0" } });
  expect(srcdoc()).toContain("padding-left: 4cm");
  expect(srcdoc()).toContain("padding-right: 0cm");
});

it("index toggle → counter CSS in srcdoc + word-toc list from h1/h3", async () => {
  await uploadDocx("<h1>Mục A</h1><h3>Phụ B</h3>");
  expect(screen.queryByTestId("word-toc")).not.toBeInTheDocument();
  await userEvent.click(screen.getByTestId("tool-index-toggle"));
  const toc = screen.getByTestId("word-toc");
  expect(toc.textContent).toContain("Mục A");
  expect(toc.textContent).toContain("Phụ B");
  expect(srcdoc()).toContain("counter-increment: h1c");
  expect(srcdoc()).toContain('content: counter(h1c) "." counter(h2c) "." counter(h3c) " "');
});

it("table borders default ON → border rule; uncheck removes it", async () => {
  await uploadDocx("<table><tbody><tr><td>1</td></tr></tbody></table>");
  const toggle = screen.getByTestId("tool-table-borders");
  expect(toggle).toBeChecked();
  expect(srcdoc()).toContain("table, th, td { border: 1px solid");
  await userEvent.click(toggle);
  expect(srcdoc()).not.toContain("table, th, td { border");
});

it("stats panel counts h1/h2/h3/table/paragraphs from loaded html", async () => {
  await uploadDocx(
    '<h1>A</h1><h2>B</h2><h3>C</h3><p>x</p><p>y</p><table><tbody><tr><td>1</td></tr></tbody></table>',
  );
  await userEvent.click(screen.getByTestId("btn-word-stats"));
  const stats = screen.getByTestId("word-stats");
  expect(stats.textContent).toContain("H1 1");
  expect(stats.textContent).toContain("H2 1");
  expect(stats.textContent).toContain("H3 1");
  expect(stats.textContent).toContain("Bảng 1");
  expect(stats.textContent).toContain("Đoạn 2");
});

