import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import * as mammoth from "mammoth";
import { toast } from "sonner";
import { ApiError, api } from "../../src/api/client";
import PreviewTabs from "../../src/components/PreviewTabs";

vi.mock("mammoth", () => ({
  convertToHtml: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    loading: vi.fn(() => "loading-1"),
    dismiss: vi.fn(),
  },
}));

vi.mock("../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      exportJob: vi.fn(),
      downloadExport: vi.fn(),
    },
  };
});

afterEach(() => {
  vi.clearAllMocks();
});

it("renders md/docx tabs (pdf tab dropped), Markdown preview on md by default", () => {
  render(<PreviewTabs jobId="5" markdown="# A" />);
  expect(screen.getByTestId("preview-md")).toBeInTheDocument();
  expect(screen.getByTestId("preview-docx")).toBeInTheDocument();
  // Plan JD: PDF preview tab removed (R51 exception) — ExportBar still exports pdf.
  expect(screen.queryByTestId("preview-pdf")).not.toBeInTheDocument();
  const frame = screen.getByTestId("preview-markdown");
  expect(frame).toBeInTheDocument();
  expect(frame.getAttribute("srcdoc") ?? "").toContain("<h1");
  expect(screen.getByTestId("panel-docs")).toBeInTheDocument();
});

it("DocStyleTools present in both tabs and its style reaches the md preview", async () => {
  render(<PreviewTabs jobId="5" markdown="# A" />);
  expect(screen.getByTestId("doc-style-tools")).toBeInTheDocument();
  expect(screen.getByTestId("tool-font-family")).toBeInTheDocument();
  // change font → md iframe srcdoc picks up the injected CSS
  await userEvent.selectOptions(screen.getByTestId("tool-font-family"), "Arial");
  await waitFor(() =>
    expect(screen.getByTestId("preview-markdown").getAttribute("srcdoc") ?? "").toContain(
      'font-family: "Arial"',
    ),
  );
  // switch to docx tab → tools stay (shared panel)
  await userEvent.click(screen.getByTestId("preview-docx"));
  expect(screen.getByTestId("tool-font-family")).toBeInTheDocument();
});

it("docx tab lazy: exportJob + downloadExport + mammoth → sanitized iframe + note", async () => {
  vi.mocked(api.exportJob).mockResolvedValue({ url: "https://r2/exports/5/docx" });
  vi.mocked(api.downloadExport).mockResolvedValue(new Blob(["PK"]));
  vi.mocked(mammoth.convertToHtml).mockResolvedValue({
    value: "<p>Chào</p><script>x</script>",
    messages: [],
  } as never);
  render(<PreviewTabs jobId="5" markdown="# A" />);
  await userEvent.click(screen.getByTestId("preview-docx"));
  const frame = await screen.findByTestId("preview-docx-frame");
  expect(api.exportJob).toHaveBeenCalledWith("5", "docx");
  expect(api.downloadExport).toHaveBeenCalledWith("5", "docx");
  expect(mammoth.convertToHtml).toHaveBeenCalledTimes(1);
  const srcdoc = frame.getAttribute("srcdoc") ?? "";
  expect(srcdoc).toContain("Chào");
  expect(srcdoc).not.toContain("script");
  expect(screen.getByTestId("docx-note")).toHaveTextContent(
    "Xem trước DOCX: giữ nội dung, mất định dạng font.",
  );
});

it("markdown prop change refreshes md preview (editor save wins over stale content)", () => {
  const { rerender } = render(<PreviewTabs jobId="5" markdown="# A" />);
  rerender(<PreviewTabs jobId="5" markdown="# B" />);
  expect(screen.getByTestId("preview-markdown").getAttribute("srcdoc") ?? "").toContain(
    "B</h1>",
  );
});

it("LLM md layout: exportJob md-layout + downloadExport → preview updates + toasts", async () => {
  vi.mocked(api.exportJob).mockResolvedValue({ url: "https://r2/exports/5/md-layout" });
  vi.mocked(api.downloadExport).mockResolvedValue(new Blob(["Bản mới **LLM**"]));
  render(<PreviewTabs jobId="5" markdown="# A" />);
  await userEvent.click(screen.getByTestId("btn-llm-layout-md"));
  expect(api.exportJob).toHaveBeenCalledWith("5", "md-layout");
  expect(api.downloadExport).toHaveBeenCalledWith("5", "md-layout");
  expect(toast.loading).toHaveBeenCalledWith("Đang gọi LLM…");
  await waitFor(() =>
    expect(screen.getByTestId("preview-markdown").getAttribute("srcdoc") ?? "").toContain(
      "Bản mới",
    ),
  );
  expect(toast.success).toHaveBeenCalledWith("Đã cập nhật layout (LLM).", {
    id: "loading-1",
  });
});

it("LLM docx layout: exportJob docx-layout + downloadExport + mammoth → preview updates", async () => {
  vi.mocked(api.exportJob).mockResolvedValue({ url: "https://r2/exports/5/docx-layout" });
  vi.mocked(api.downloadExport).mockResolvedValue(new Blob(["PK"]));
  vi.mocked(mammoth.convertToHtml).mockResolvedValue({
    value: "<p>Layout mới</p>",
    messages: [],
  } as never);
  render(<PreviewTabs jobId="5" markdown="# A" />);
  await userEvent.click(screen.getByTestId("preview-docx"));
  await screen.findByTestId("preview-docx-frame");
  await userEvent.click(screen.getByTestId("btn-llm-layout-docx"));
  expect(api.exportJob).toHaveBeenCalledWith("5", "docx-layout");
  expect(api.downloadExport).toHaveBeenCalledWith("5", "docx-layout");
  await waitFor(() =>
    expect(screen.getByTestId("preview-docx-frame").getAttribute("srcdoc") ?? "").toContain(
      "Layout mới",
    ),
  );
  expect(toast.success).toHaveBeenCalledWith("Đã cập nhật layout (LLM).", {
    id: "loading-1",
  });
});

it("LLM layout failure: toast.error with mapped message and loading toast killed", async () => {
  vi.mocked(api.exportJob).mockRejectedValue(new ApiError("LLM lỗi."));
  render(<PreviewTabs jobId="5" markdown="# A" />);
  await userEvent.click(screen.getByTestId("btn-llm-layout-md"));
  expect(toast.loading).toHaveBeenCalledWith("Đang gọi LLM…");
  await waitFor(() => expect(toast.error).toHaveBeenCalledWith("LLM lỗi."));
  expect(toast.dismiss).toHaveBeenCalledWith("loading-1");
  // preview content untouched on failure
  expect(screen.getByTestId("preview-markdown").getAttribute("srcdoc") ?? "").toContain("<h1");
});

it("shows ApiError detail in docs-error when docx export fails", async () => {
  vi.mocked(api.exportJob).mockRejectedValue(new ApiError("Xuất file thất bại."));
  render(<PreviewTabs jobId="5" markdown="# A" />);
  await userEvent.click(screen.getByTestId("preview-docx"));
  expect(await screen.findByTestId("docs-error")).toHaveTextContent("Xuất file thất bại.");
  // R51: inline docs-error kept; toast mirrors it (R59a).
  expect(toast.error).toHaveBeenCalledWith("Xuất file thất bại.");
  // failed docx frame never appears
  await waitFor(() => expect(screen.queryByTestId("preview-docx-frame")).not.toBeInTheDocument());
});
