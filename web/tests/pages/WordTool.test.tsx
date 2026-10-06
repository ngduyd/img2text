import { render, screen } from "@testing-library/react";
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

it("renders word-tool wrapper: URL input, tools row, empty state, export disabled", () => {
  render(<WordTool />);
  expect(screen.getByTestId("word-tool")).toBeInTheDocument();
  expect(screen.getByLabelText("URL tài liệu")).toBe(screen.getByTestId("input-word-url"));
  expect(screen.getByTestId("btn-word-load")).toHaveTextContent("Tải URL");
  expect(screen.getByText("Chưa có tài liệu")).toBeInTheDocument();
  expect(screen.getByTestId("btn-word-to-md")).toBeDisabled();
  const exportBtn = screen.getByTestId("btn-word-export-docx");
  expect(exportBtn).toBeDisabled();
  expect(exportBtn).toHaveAttribute("title", "Xuất sau khi có job OCR");
});

it("URL fetch fail → word-url-error CORS message", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
  render(<WordTool />);
  await userEvent.type(screen.getByTestId("input-word-url"), "https://vi.example/tai-lieu.docx");
  await userEvent.click(screen.getByTestId("btn-word-load"));
  expect(await screen.findByTestId("word-url-error")).toHaveTextContent(
    "Không tải được URL từ trình duyệt (CORS): dùng Tải file .docx",
  );
  // preview stays in empty state (no doc loaded)
  expect(screen.queryByTestId("word-preview")).not.toBeInTheDocument();
});

it("upload docx → mammoth → sanitized iframe srcdoc", async () => {
  await uploadDocx("<h1>Chào</h1><script>alert(1)</script>");
  expect(mammoth.convertToHtml).toHaveBeenCalledTimes(1);
  const srcdoc = screen.getByTestId("word-preview").getAttribute("srcdoc") ?? "";
  expect(screen.getByTestId("word-preview")).toHaveAttribute("sandbox", "");
  expect(srcdoc).toContain("Chào");
  expect(srcdoc).not.toContain("script");
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

it("btn-word-to-md downloads markdown blob via createObjectURL", async () => {
  const createObjectURL = vi.fn((_blob: Blob) => "blob:mock");
  URL.createObjectURL = createObjectURL;
  URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  await uploadDocx(
    "<h1>Tiêu đề</h1><p>Nội dung</p><ul><li>Mục</li></ul><table><tbody><tr><td>c</td></tr></tbody></table>",
  );
  await userEvent.click(screen.getByTestId("btn-word-to-md"));
  expect(createObjectURL).toHaveBeenCalledTimes(1);
  const blob = createObjectURL.mock.calls[0][0] as Blob;
  expect(blob.type).toContain("text/markdown");
  const text = await blob.text();
  expect(text).toContain("# Tiêu đề");
  expect(text).toContain("Nội dung");
  expect(text).toContain("- Mục");
  expect(text).toContain("<table");
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:mock");
});
