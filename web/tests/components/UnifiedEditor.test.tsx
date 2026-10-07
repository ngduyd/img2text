import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import * as mammoth from "mammoth";
import { toast } from "sonner";
import { ApiError, api } from "../../src/api/client";
import type { Job } from "../../src/api/types";
import UnifiedEditor from "../../src/components/UnifiedEditor";

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
      putMdLayoutContent: vi.fn(),
      putLayoutStyle: vi.fn(),
    },
  };
});

const JOB: Job = {
  id: 5,
  status: "done",
  file_type: "pdf",
  page_count: 1,
  error: null,
  result: null,
  created_at: "2026-01-02T03:04:05Z",
  started_at: null,
  finished_at: null,
  output_format: "md",
  layout_cache: { md: false, docx: false },
  layout_style: null,
};

/** Harness có state editing thật (btn-edit-source toggle như JobDetail control). */
function Harness({ job, markdown = "# Artifact" }: { job: Job; markdown?: string }) {
  const [editing, setEditing] = useState(false);
  const [client] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: false } } }),
  );
  return (
    <QueryClientProvider client={client}>
      <UnifiedEditor
        jobId={String(job.id)}
        job={job}
        markdown={markdown}
        editing={editing}
        onEditingChange={setEditing}
      />
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.exportJob).mockResolvedValue({ url: "" });
  vi.mocked(api.downloadExport).mockResolvedValue(new Blob(["# Artifact"]));
  vi.mocked(mammoth.convertToHtml).mockResolvedValue({
    value: "<p>Chào</p>",
    messages: [],
  } as never);
});

it("md cache miss: exportJob md-layout + layout-loading spinner → content renders + badge chưa lưu", async () => {
  let release: (() => void) | null = null;
  vi.mocked(api.exportJob).mockImplementation(
    () =>
      new Promise<{ url: string }>((resolve) => {
        release = () => resolve({ url: "" });
      }),
  );
  vi.mocked(api.downloadExport).mockResolvedValue(new Blob(["# Mới từ LLM"]));
  render(<Harness job={JOB} />);
  expect(screen.getByTestId("layout-loading")).toHaveTextContent("Đang vẽ layout bằng LLM…");
  expect(screen.getByTestId("layout-badge")).toHaveTextContent("Layout chưa lưu");
  expect(api.exportJob).toHaveBeenCalledWith("5", "md-layout");
  await act(async () => release?.());
  const frame = await screen.findByTestId("preview-markdown");
  expect(frame.getAttribute("srcdoc") ?? "").toContain("Mới từ LLM");
  expect(screen.queryByTestId("layout-loading")).toBeNull();
});

it("md cache hit (layout_cache.md=true): badge đã lưu + exportJob/downloadExport path vẫn chạy (mock, không LLM thật)", async () => {
  vi.mocked(api.downloadExport).mockResolvedValue(new Blob(["# Cached"]));
  render(<Harness job={{ ...JOB, layout_cache: { md: true, docx: true } }} />);
  expect(screen.getByTestId("layout-badge")).toHaveTextContent("Layout đã lưu");
  const frame = await screen.findByTestId("preview-markdown");
  expect(api.exportJob).toHaveBeenCalledWith("5", "md-layout");
  expect(api.downloadExport).toHaveBeenCalledWith("5", "md-layout");
  // renderMarkdown sanitize contract (preview-markdown giữ nguyên testid, R51)
  expect(frame.getAttribute("srcdoc") ?? "").toContain("<h1");
});

it("layout_style đã lưu → client CSS vào md iframe (contract M1)", async () => {
  render(
    <Harness
      job={{
        ...JOB,
        layout_cache: { md: true, docx: false },
        layout_style: { fontFamily: "Arial", align: "center" },
      }}
    />,
  );
  const frame = await screen.findByTestId("preview-markdown");
  const srcdoc = frame.getAttribute("srcdoc") ?? "";
  expect(srcdoc).toContain('font-family: "Arial"');
  expect(srcdoc).toContain("text-align: center");
});

it("switch mode: word → exportJob docx-layout + mammoth iframe + word tools; md → toolbar path, không word tools", async () => {
  const user = userEvent.setup();
  render(<Harness job={{ ...JOB, layout_cache: { md: true, docx: false } }} />);
  await screen.findByTestId("preview-markdown");
  expect(screen.queryByTestId("word-tb-align-center")).not.toBeInTheDocument();
  expect(screen.getByTestId("btn-edit-source")).toBeInTheDocument();

  await user.click(screen.getByTestId("switch-mode-word"));
  await screen.findByTestId("preview-docx-frame");
  expect(api.exportJob).toHaveBeenCalledWith("5", "docx-layout");
  expect(screen.getByTestId("word-tb-align-center")).toBeInTheDocument();
  expect(screen.queryByTestId("btn-edit-source")).not.toBeInTheDocument();
  expect(screen.getByText("Sửa chữ ở dạng Markdown.")).toBeInTheDocument();
  // badge theo mode: docx chưa cache
  expect(screen.getByTestId("layout-badge")).toHaveTextContent("Layout chưa lưu");

  const mdCalls = vi.mocked(api.exportJob).mock.calls.filter((c) => c[1] === "md-layout").length;
  await user.click(screen.getByTestId("switch-mode-md"));
  expect(screen.getByTestId("preview-markdown")).toBeInTheDocument();
  expect(screen.queryByTestId("word-tb-align-center")).not.toBeInTheDocument();
  // đã load rồi → không chạy lại flow md
  expect(vi.mocked(api.exportJob).mock.calls.filter((c) => c[1] === "md-layout").length).toBe(
    mdCalls,
  );
});

it("default mode = word khi output_format docx (binding)", async () => {
  render(<Harness job={{ ...JOB, output_format: "docx" }} />);
  expect(screen.getByTestId("switch-mode-word")).toHaveAttribute("aria-pressed", "true");
  await screen.findByTestId("preview-docx-frame");
  expect(api.exportJob).toHaveBeenCalledWith("5", "docx-layout");
});

it("md source: btn-edit-source → MdToolbar + textarea; handleFormat bold; Lưu → putMdLayoutContent + toast", async () => {
  const user = userEvent.setup();
  render(<Harness job={JOB} />);
  await screen.findByTestId("preview-markdown");
  await user.click(screen.getByTestId("btn-edit-source"));
  const ta = (await screen.findByTestId("textarea-markdown")) as HTMLTextAreaElement;
  expect(screen.getByTestId("md-tb-bold")).toBeInTheDocument();
  // handleFormat pattern (applyMdOp): bold quanh selection
  ta.setSelectionRange(0, 3);
  await user.click(screen.getByTestId("md-tb-bold"));
  expect((screen.getByTestId("textarea-markdown") as HTMLTextAreaElement).value).toContain(
    "**# A**",
  );
  await user.click(screen.getByTestId("btn-save-layout"));
  expect(api.putMdLayoutContent).toHaveBeenCalledWith("5", "**# A**rtifact");
  expect(toast.success).toHaveBeenCalledWith("Đã lưu.");
});

it("word style: đổi align → btn-save-style → putLayoutStyle (objectContaining) + toast", async () => {
  const user = userEvent.setup();
  render(<Harness job={JOB} />);
  await user.click(screen.getByTestId("switch-mode-word"));
  await screen.findByTestId("preview-docx-frame");
  await user.click(screen.getByTestId("word-tb-align-center"));
  await user.click(screen.getByTestId("btn-save-style"));
  expect(api.putLayoutStyle).toHaveBeenCalledWith(
    "5",
    expect.objectContaining({ align: "center" }),
  );
  expect(toast.success).toHaveBeenCalledWith("Đã lưu.");
});

it("word tools hydrate từ job.layout_style (session trước đã lưu)", async () => {
  const user = userEvent.setup();
  render(
    <Harness job={{ ...JOB, layout_style: { align: "center", fontSize: 20 } }} />,
  );
  await user.click(screen.getByTestId("switch-mode-word"));
  await screen.findByTestId("preview-docx-frame");
  expect(screen.getByTestId("word-tb-align-center")).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByTestId("tool-font-size")).toHaveValue(20);
});

it("flow lỗi → layout-error + btn-retry-layout + toast.error; retry chạy lại flow", async () => {
  const user = userEvent.setup();
  vi.mocked(api.exportJob).mockRejectedValueOnce(new ApiError("LLM lỗi."));
  render(<Harness job={JOB} />);
  expect(await screen.findByTestId("layout-error")).toHaveTextContent("LLM lỗi.");
  expect(toast.error).toHaveBeenCalledWith("LLM lỗi.");
  await user.click(screen.getByTestId("btn-retry-layout"));
  expect(await screen.findByTestId("preview-markdown")).toBeInTheDocument();
  expect(screen.queryByTestId("layout-error")).toBeNull();
});
