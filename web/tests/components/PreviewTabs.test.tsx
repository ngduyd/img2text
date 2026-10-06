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

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

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

it("renders three tabs and shows MarkdownPreview on md by default", () => {
  render(<PreviewTabs jobId="5" markdown="# A" />);
  for (const tab of ["preview-md", "preview-pdf", "preview-docx"]) {
    expect(screen.getByTestId(tab)).toBeInTheDocument();
  }
  expect(screen.getByTestId("preview-markdown")).toBeInTheDocument();
  expect(screen.getByTestId("panel-docs")).toBeInTheDocument();
});

it("pdf tab lazy: exportJob called once, iframe src set; reactivation no re-call", async () => {
  vi.mocked(api.exportJob).mockResolvedValue({ url: "https://r2/exports/5/pdf" });
  render(<PreviewTabs jobId="5" markdown="# A" />);
  expect(api.exportJob).not.toHaveBeenCalled();
  await userEvent.click(screen.getByTestId("preview-pdf"));
  const frame = await screen.findByTitle("Xem trước PDF");
  expect(frame).toHaveAttribute("src", "https://r2/exports/5/pdf");
  expect(api.exportJob).toHaveBeenCalledTimes(1);
  expect(api.exportJob).toHaveBeenCalledWith("5", "pdf");
  // R59a: background export success toasts.
  expect(toast.success).toHaveBeenCalledWith("Đã tạo bản xuất.");
  // reactivation (md → pdf) hits the state cache — no duplicate call
  await userEvent.click(screen.getByTestId("preview-md"));
  await userEvent.click(screen.getByTestId("preview-pdf"));
  expect(screen.getByTitle("Xem trước PDF")).toBeInTheDocument();
  expect(api.exportJob).toHaveBeenCalledTimes(1);
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

it("shows ApiError detail in docs-error when export fails", async () => {
  vi.mocked(api.exportJob).mockRejectedValue(new ApiError("Xuất file thất bại."));
  render(<PreviewTabs jobId="5" markdown="# A" />);
  await userEvent.click(screen.getByTestId("preview-pdf"));
  expect(await screen.findByTestId("docs-error")).toHaveTextContent(
    "Xuất file thất bại.",
  );
  // R51: inline docs-error kept; toast mirrors it (R59a).
  expect(toast.error).toHaveBeenCalledWith("Xuất file thất bại.");
  // failed pdf frame never appears
  await waitFor(() =>
    expect(screen.queryByTitle("Xem trước PDF")).not.toBeInTheDocument(),
  );
});
