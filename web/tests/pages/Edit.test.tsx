import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as mammoth from "mammoth";
import { toast } from "sonner";
import { api, ApiError } from "../../src/api/client";
import type { Job } from "../../src/api/types";
import Edit from "../../src/pages/Edit";

vi.mock("mammoth", () => ({ convertToHtml: vi.fn() }));

vi.mock("sonner", () => ({
  toast: { loading: vi.fn(), success: vi.fn(), error: vi.fn() },
}));

vi.mock("../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      getJob: vi.fn(),
      downloadExport: vi.fn(),
    },
  };
});

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderEdit(route = "/edit") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Edit />
    </MemoryRouter>,
  );
}

function previewSrcdoc(): string {
  return screen.getByTestId("preview-markdown").getAttribute("srcdoc") ?? "";
}

function wordSrcdoc(): string {
  return screen.getByTestId("word-preview").getAttribute("srcdoc") ?? "";
}

async function openWordMode() {
  await userEvent.click(screen.getByTestId("edit-tab-word"));
}

async function uploadDocx(value: string) {
  vi.mocked(mammoth.convertToHtml).mockResolvedValue({ value, messages: [] } as never);
  await openWordMode();
  const file = new File(["PK"], "van-ban.docx", {
    type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  });
  await userEvent.upload(screen.getByTestId("input-word-file"), file);
  await screen.findByTestId("word-preview");
}

// ---------- /edit: mode md mặc định + chuyển mode ----------

it("renders edit-page in md mode: editor, toolbar, live preview, shared tools; no word upload", () => {
  renderEdit();
  expect(screen.getByTestId("edit-page")).toBeInTheDocument();
  expect(screen.getByTestId("edit-tab-md")).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByTestId("edit-md-input")).toBeInTheDocument();
  for (const t of ["edit-md-bold", "edit-md-h1", "edit-md-h2"]) {
    expect(screen.getByTestId(t)).toBeInTheDocument();
  }
  expect(screen.getByTestId("preview-markdown")).toBeInTheDocument();
  expect(screen.getByTestId("edit-tools")).toBeInTheDocument();
  for (const t of [
    "tool-font-family",
    "tool-font-size",
    "tool-index-toggle",
    "tool-margin-left",
    "tool-margin-right",
    "tool-table-borders",
  ]) {
    expect(screen.getByTestId(t)).toBeInTheDocument();
  }
  expect(screen.queryByTestId("input-word-file")).not.toBeInTheDocument();
});

it("mode switch md → word → md swaps panes, tools row stays", async () => {
  renderEdit();
  await openWordMode();
  expect(screen.getByTestId("edit-tab-word")).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByTestId("word-upload")).toBeInTheDocument();
  expect(screen.getByTestId("input-word-file")).toBeInTheDocument();
  expect(screen.queryByTestId("edit-md-input")).not.toBeInTheDocument();
  expect(screen.getByTestId("edit-tools")).toBeInTheDocument();
  await userEvent.click(screen.getByTestId("edit-tab-md"));
  expect(screen.getByTestId("edit-md-input")).toBeInTheDocument();
  expect(screen.queryByTestId("input-word-file")).not.toBeInTheDocument();
  expect(screen.getByTestId("edit-tools")).toBeInTheDocument();
});

// ---------- md editor toolbar ----------

it("bold wraps selection with **", async () => {
  renderEdit();
  const ta = screen.getByTestId("edit-md-input") as HTMLTextAreaElement;
  fireEvent.change(ta, { target: { value: "đẹp quá" } });
  ta.setSelectionRange(0, ta.value.length);
  await userEvent.click(screen.getByTestId("edit-md-bold"));
  expect(ta).toHaveValue("**đẹp quá**");
});

it("H1 prefixes line with #, H2 with ##", async () => {
  renderEdit();
  const ta = screen.getByTestId("edit-md-input") as HTMLTextAreaElement;
  fireEvent.change(ta, { target: { value: "Tiêu đề" } });
  ta.setSelectionRange(0, ta.value.length);
  await userEvent.click(screen.getByTestId("edit-md-h1"));
  expect(ta).toHaveValue("# Tiêu đề");

  fireEvent.change(ta, { target: { value: "Mục" } });
  ta.setSelectionRange(0, ta.value.length);
  await userEvent.click(screen.getByTestId("edit-md-h2"));
  expect(ta).toHaveValue("## Mục");
});

// ---------- live preview (debounce 300ms) ----------

it("live preview renders markdown after debounce", async () => {
  renderEdit();
  expect(previewSrcdoc()).not.toContain("<h1");
  await userEvent.type(screen.getByTestId("edit-md-input"), "# Xin");
  await waitFor(() => expect(previewSrcdoc()).toContain("<h1"), { timeout: 2000 });
  expect(previewSrcdoc()).toContain("Xin");
});

// ---------- tools style inject lên md preview ----------

it("font family + size tools change css block in md preview srcdoc", async () => {
  renderEdit();
  expect(previewSrcdoc()).toContain('font-family: "system-ui"');
  await userEvent.selectOptions(screen.getByTestId("tool-font-family"), "Arial");
  expect(previewSrcdoc()).toContain('font-family: "Arial"');
  fireEvent.change(screen.getByTestId("tool-font-size"), { target: { value: "24" } });
  expect(previewSrcdoc()).toContain("font-size: 24px");
});

it("margins + table borders tools change css block in md preview srcdoc", async () => {
  renderEdit();
  expect(previewSrcdoc()).toContain("padding-left: 2.5cm");
  fireEvent.change(screen.getByTestId("tool-margin-left"), { target: { value: "4" } });
  fireEvent.change(screen.getByTestId("tool-margin-right"), { target: { value: "0" } });
  expect(previewSrcdoc()).toContain("padding-left: 4cm");
  expect(previewSrcdoc()).toContain("padding-right: 0cm");
  expect(previewSrcdoc()).toContain("table, th, td { border: 1px solid");
  await userEvent.click(screen.getByTestId("tool-table-borders"));
  expect(previewSrcdoc()).not.toContain("table, th, td { border");
});

it("index toggle → counter CSS in preview + word-toc from md headings", async () => {
  renderEdit();
  await userEvent.type(screen.getByTestId("edit-md-input"), "# Mục A");
  await userEvent.click(screen.getByTestId("tool-index-toggle"));
  const toc = screen.getByTestId("word-toc");
  expect(toc.textContent).toContain("Mục A");
  expect(previewSrcdoc()).toContain("counter-increment: h1c");
  expect(previewSrcdoc()).toContain('content: counter(h1c) "." counter(h2c) "." counter(h3c) " "');
});

// ---------- word mode (ported WordTool flow) ----------

it("word empty state: upload card + tools + preview placeholder; no export controls", async () => {
  renderEdit();
  await openWordMode();
  expect(screen.getByTestId("word-tool")).toBeInTheDocument();
  expect(screen.getByTestId("word-upload")).toBeInTheDocument();
  expect(screen.getByTestId("edit-tools")).toBeInTheDocument();
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
  renderEdit();
  await uploadDocx("<h1>Chào</h1><script>alert(1)</script>");
  expect(mammoth.convertToHtml).toHaveBeenCalledTimes(1);
  const doc = wordSrcdoc();
  expect(screen.getByTestId("word-preview")).toHaveAttribute("sandbox", "");
  expect(doc).toContain("Chào");
  expect(doc).not.toContain("script");
  expect(doc).toContain('<style id="word-style">');
});

it("word tools: font + margins + table borders change word preview srcdoc", async () => {
  renderEdit();
  await uploadDocx("<h1>A</h1><table><tbody><tr><td>1</td></tr></tbody></table>");
  expect(wordSrcdoc()).toContain('font-family: "system-ui"');
  await userEvent.selectOptions(screen.getByTestId("tool-font-family"), "Arial");
  expect(wordSrcdoc()).toContain('font-family: "Arial"');
  fireEvent.change(screen.getByTestId("tool-font-size"), { target: { value: "24" } });
  expect(wordSrcdoc()).toContain("font-size: 24px");
  fireEvent.change(screen.getByTestId("tool-margin-left"), { target: { value: "4" } });
  expect(wordSrcdoc()).toContain("padding-left: 4cm");
  expect(wordSrcdoc()).toContain("padding-right: 2.5cm");
  expect(wordSrcdoc()).toContain("table, th, td { border: 1px solid");
  await userEvent.click(screen.getByTestId("tool-table-borders"));
  expect(wordSrcdoc()).not.toContain("table, th, td { border");
});

it("word index toggle → counter CSS + word-toc from mammoth headings", async () => {
  renderEdit();
  await uploadDocx("<h1>Mục A</h1><h3>Phụ B</h3>");
  expect(screen.queryByTestId("word-toc")).not.toBeInTheDocument();
  await userEvent.click(screen.getByTestId("tool-index-toggle"));
  const toc = screen.getByTestId("word-toc");
  expect(toc.textContent).toContain("Mục A");
  expect(toc.textContent).toContain("Phụ B");
  expect(wordSrcdoc()).toContain("counter-increment: h1c");
});

it("stats panel counts h1/h2/h3/table/paragraphs from loaded html", async () => {
  renderEdit();
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

// ---------- ?job= prefill ----------

const DONE_JOB = {
  id: 7,
  status: "done",
  file_type: "png",
  page_count: 1,
  error: null,
  output_format: "md",
  result: { model_version: "m", gpu_seconds: 0, warnings: [], markdown: "# Gốc", edited_markdown: null, pages: [] },
} as unknown as Job;

it("?job= md: GET job → textarea prefilled with edited_markdown", async () => {
  vi.mocked(api.getJob).mockResolvedValue({
    ...DONE_JOB,
    result: { ...(DONE_JOB.result as object), edited_markdown: "# Đã sửa" },
  } as Job);
  renderEdit("/edit?job=7");
  expect(api.getJob).toHaveBeenCalledWith("7");
  const ta = await screen.findByTestId("edit-md-input");
  await waitFor(() => expect(ta).toHaveValue("# Đã sửa"));
});

it("?job= md: edited_markdown null → fallback result.markdown", async () => {
  vi.mocked(api.getJob).mockResolvedValue(DONE_JOB);
  renderEdit("/edit?job=8");
  const ta = await screen.findByTestId("edit-md-input");
  await waitFor(() => expect(ta).toHaveValue("# Gốc"));
});

it("?job= docx: default mode word → downloadExport blob → mammoth preview", async () => {
  vi.mocked(api.getJob).mockResolvedValue({ ...DONE_JOB, output_format: "docx" } as Job);
  vi.mocked(api.downloadExport).mockResolvedValue(new Blob(["PK"]));
  vi.mocked(mammoth.convertToHtml).mockResolvedValue({
    value: "<h1>Từ job</h1>",
    messages: [],
  } as never);
  renderEdit("/edit?job=7");
  const frame = await screen.findByTestId("word-preview");
  expect(api.downloadExport).toHaveBeenCalledWith("7", "docx");
  await waitFor(() => expect(frame.getAttribute("srcdoc") ?? "").toContain("Từ job"));
  expect(screen.getByTestId("edit-tab-word")).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByTestId("input-word-file")).toBeInTheDocument();
});

it("?job= fetch failure → toast.error with mapped message", async () => {
  vi.mocked(api.getJob).mockRejectedValue(new ApiError("Forbidden."));
  renderEdit("/edit?job=7");
  await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Forbidden."));
  expect(screen.getByTestId("edit-md-input")).toBeInTheDocument();
});
