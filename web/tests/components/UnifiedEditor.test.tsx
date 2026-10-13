import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
      patchLayoutContent: vi.fn(),
      putLayoutStyle: vi.fn(),
      getDocxHtml: vi.fn(),
      putDocxHtml: vi.fn(),
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
  text_version: 1,
};

/** Harness có state editing thật (btn-edit-doc header toggle như JobDetail control). */
function Harness({
  job,
  markdown = "# Artifact",
  hostRef,
}: {
  job: Job;
  markdown?: string;
  hostRef?: { current: HTMLElement | null };
}) {
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
        hostRef={hostRef}
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
  // Plan M3: mặc định chưa có docx.html cache → word flow đi fallback mammoth.
  vi.mocked(api.getDocxHtml).mockResolvedValue(null);
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
  const editor = await screen.findByTestId("md-editor");
  await waitFor(() => expect(editor.querySelector("textarea")?.value).toContain("Mới từ LLM"));
  expect(screen.queryByTestId("layout-loading")).toBeNull();
});

it("md cache hit (layout_cache.md=true): badge đã lưu + exportJob/downloadExport path vẫn chạy (mock, không LLM thật)", async () => {
  vi.mocked(api.downloadExport).mockResolvedValue(new Blob(["# Cached"]));
  render(<Harness job={{ ...JOB, layout_cache: { md: true, docx: true } }} />);
  expect(screen.getByTestId("layout-badge")).toHaveTextContent("Layout đã lưu");
  const editor = await screen.findByTestId("md-editor");
  expect(api.exportJob).toHaveBeenCalledWith("5", "md-layout");
  expect(api.downloadExport).toHaveBeenCalledWith("5", "md-layout");
  // value wiring: md-layout vào MDEditor + preview split render heading
  await waitFor(() => expect(editor.querySelector("textarea")?.value).toContain("# Cached"));
  expect(editor.querySelector(".w-md-editor-preview")?.textContent).toContain("Cached");
});

it("layout_style đã lưu → client CSS scope preview pane md (contract M1, M5 không iframe)", async () => {
  render(
    <Harness
      job={{
        ...JOB,
        layout_cache: { md: true, docx: false },
        layout_style: { fontFamily: "Arial", align: "center" },
      }}
    />,
  );
  const editor = await screen.findByTestId("md-editor");
  const css = editor.querySelector("style")?.textContent ?? "";
  expect(css).toContain(".md-pane .w-md-editor-preview");
  expect(css).toContain('font-family: "Arial"');
  expect(css).toContain("text-align: center");
});

it("switch mode: word → exportJob docx-layout + Tiptap editor + word tools; md → toolbar path, không word tools", async () => {
  const user = userEvent.setup();
  render(<Harness job={{ ...JOB, layout_cache: { md: true, docx: false } }} />);
  await screen.findByTestId("md-editor");
  expect(screen.queryByTestId("word-tb-align-center")).not.toBeInTheDocument();

  await user.click(screen.getByTestId("switch-mode-word"));
  await screen.findByTestId("preview-docx-frame");
  expect(api.exportJob).toHaveBeenCalledWith("5", "docx-layout");
  expect(screen.getByTestId("word-tb-align-center")).toBeInTheDocument();
  // M5: md node unmount khi sang word (không rò)
  expect(screen.queryByTestId("md-editor")).toBeNull();
  expect(screen.queryByTestId("btn-save-layout")).toBeNull();
  // Plan M3: hint "Sửa chữ ở dạng Markdown" BỎ + content toolbar single-row + nút Lưu.
  expect(screen.queryByText("Sửa chữ ở dạng Markdown.")).toBeNull();
  expect(screen.getByTestId("word-toolbar")).toBeInTheDocument();
  expect(screen.getByTestId("btn-save-layout-word")).toBeInTheDocument();
  // badge theo mode: docx chưa cache
  expect(screen.getByTestId("layout-badge")).toHaveTextContent("Layout chưa lưu");
  // M4: editor Tiptap thay iframe — container giữ testid, nội dung là .ProseMirror contenteditable
  const pane = screen.getByTestId("preview-docx-frame");
  expect(pane.className).toContain("min-h-[60vh]");
  await waitFor(() =>
    expect(pane.querySelector(".ProseMirror")).toHaveAttribute("contenteditable", "true"),
  );

  const mdCalls = vi.mocked(api.exportJob).mock.calls.filter((c) => c[1] === "md-layout").length;
  await user.click(screen.getByTestId("switch-mode-md"));
  expect(screen.getByTestId("md-editor")).toBeInTheDocument();
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

it("M5: md mode = MDEditor (value/onChange wiring); Lưu → PATCH layout-content + toast", async () => {
  const user = userEvent.setup();
  vi.mocked(api.patchLayoutContent).mockResolvedValue({ ok: true });
  render(<Harness job={JOB} />);
  const editor = await screen.findByTestId("md-editor");
  const ta = editor.querySelector("textarea") as HTMLTextAreaElement;
  expect(ta.value).toBe("# Artifact");
  fireEvent.change(ta, { target: { value: "# Đã sửa" } });
  expect(ta.value).toBe("# Đã sửa");
  await user.click(screen.getByTestId("btn-save-layout"));
  expect(api.patchLayoutContent).toHaveBeenCalledWith("5", "# Đã sửa");
  expect(toast.success).toHaveBeenCalledWith("Đã lưu.");
});

/** Lane I Task 4: XÓA nút proofread/refresh + panel suggestions (server route giữ nguyên). */
it("lane I task 4: không còn btn-proofread/btn-refresh-proofread/suggestions-panel trong DOM", async () => {
  render(<Harness job={JOB} />);
  await screen.findByTestId("md-editor");
  expect(screen.queryByTestId("btn-proofread")).toBeNull();
  expect(screen.queryByTestId("btn-refresh-proofread")).toBeNull();
  expect(screen.queryByTestId("suggestions-panel")).toBeNull();
  expect(screen.queryByTestId("proofread-badge")).toBeNull();
  // word mode cũng không
  await userEvent.click(screen.getByTestId("switch-mode-word"));
  await screen.findByTestId("preview-docx-frame");
  expect(screen.queryByTestId("btn-proofread")).toBeNull();
  expect(screen.queryByTestId("suggestions-panel")).toBeNull();
});

it("word style: đổi line spacing → btn-save-style → putLayoutStyle (objectContaining) + toast", async () => {
  const user = userEvent.setup();
  render(<Harness job={JOB} />);
  await user.click(screen.getByTestId("switch-mode-word"));
  await screen.findByTestId("preview-docx-frame");
  await user.selectOptions(screen.getByTestId("word-style-spacing"), "1");
  await user.click(screen.getByTestId("btn-save-style"));
  expect(api.putLayoutStyle).toHaveBeenCalledWith(
    "5",
    expect.objectContaining({ spacing: "1" }),
  );
  expect(toast.success).toHaveBeenCalledWith("Đã lưu.");
});

it("word tools hydrate từ job.layout_style (session trước đã lưu)", async () => {
  const user = userEvent.setup();
  render(
    <Harness job={{ ...JOB, layout_style: { align: "center", fontSize: 20, spacing: "1" } }} />,
  );
  await user.click(screen.getByTestId("switch-mode-word"));
  await screen.findByTestId("preview-docx-frame");
  expect(screen.getByTestId("word-style-spacing")).toHaveValue("1");
});

it("DocStyleTools word: giữ controls trang-level; gỡ control trùng toolbar Tiptap (R51 exception theo lệnh user)", async () => {
  const user = userEvent.setup();
  render(<Harness job={JOB} />);
  await user.click(screen.getByTestId("switch-mode-word"));
  await screen.findByTestId("preview-docx-frame");
  screen.getByTestId("doc-style-tools");
  // còn lại: margin / line spacing / TOC / indent / viền bảng (trang-level)
  for (const id of [
    "tool-margin-left",
    "tool-margin-right",
    "word-style-spacing",
    "tool-index-toggle",
    "word-style-indent-in",
    "word-style-indent-out",
    "tool-table-borders",
  ])
    expect(screen.getByTestId(id)).toBeInTheDocument();
  // gỡ: trùng toolbar Tiptap theo vùng chọn — không render nữa
  for (const id of [
    "tool-font-family",
    "tool-font-size",
    "word-style-align-left",
    "word-style-align-center",
    "word-style-align-justify",
    "word-style-underline",
  ])
    expect(screen.queryByTestId(id)).toBeNull();
});

it("flow lỗi → layout-error + btn-retry-layout-error (review r1 P1: không trùng header) + toast.error; retry chạy lại flow", async () => {
  const user = userEvent.setup();
  vi.mocked(api.exportJob).mockRejectedValueOnce(new ApiError("LLM lỗi."));
  render(<Harness job={JOB} />);
  expect(await screen.findByTestId("layout-error")).toHaveTextContent("LLM lỗi.");
  expect(toast.error).toHaveBeenCalledWith("LLM lỗi.");
  await user.click(screen.getByTestId("btn-retry-layout-error"));
  expect(await screen.findByTestId("md-editor")).toBeInTheDocument();
  expect(screen.queryByTestId("layout-error")).toBeNull();
});

it("Plan M4: word toolbar = đúng 1 container row (overflow-x-auto, gap-2, không flex-wrap) + đủ lệnh trên editor Tiptap", async () => {
  const user = userEvent.setup();
  render(<Harness job={JOB} />);
  await user.click(screen.getByTestId("switch-mode-word"));
  await screen.findByTestId("preview-docx-frame");
  const root = screen.getByTestId("word-toolbar");
  const rows = root.querySelectorAll('[role="toolbar"]');
  expect(rows).toHaveLength(1);
  expect(rows[0]).toHaveClass("overflow-x-auto");
  expect(rows[0]).toHaveClass("gap-2");
  expect(rows[0]).not.toHaveClass("flex-wrap");
  const ids = [
    "word-tb-undo",
    "word-tb-redo",
    "word-tb-font",
    "word-tb-size",
    "word-tb-bold",
    "word-tb-italic",
    "word-tb-underline",
    "word-tb-align-left",
    "word-tb-align-center",
    "word-tb-align-right",
    "word-tb-align-justify",
    "word-tb-list-ul",
    "word-tb-list-ol",
    "word-tb-table",
    "word-tb-clear",
  ];
  for (const id of ids) expect(screen.getByTestId(id)).toBeInTheDocument();
  // M4: không còn iframe — editor Tiptap (.ProseMirror contenteditable) trong container
  const pane = screen.getByTestId("preview-docx-frame") as HTMLElement;
  expect(pane.querySelector("iframe")).toBeNull();
  await waitFor(() =>
    expect(pane.querySelector(".ProseMirror")).toHaveAttribute("contenteditable", "true"),
  );
});

it("Plan M4: Lưu word → editor.getHTML() → putDocxHtml + toast 'Đã lưu.' + invalidate job", async () => {
  const user = userEvent.setup();
  render(<Harness job={{ ...JOB, layout_cache: { md: true, docx: false } }} />);
  await user.click(screen.getByTestId("switch-mode-word"));
  const pane = await screen.findByTestId("preview-docx-frame");
  await waitFor(() => expect(pane.querySelector(".ProseMirror")).toHaveTextContent("Chào"));
  await user.click(screen.getByTestId("btn-save-layout-word"));
  expect(api.putDocxHtml).toHaveBeenCalledWith("5", "<p>Chào</p>");
  expect(toast.success).toHaveBeenCalledWith("Đã lưu.");
});

it("Plan M3: layout_cache.docx_html=true → GET docx.html (getDocxHtml), KHÔNG exportJob/mammoth", async () => {
  vi.mocked(api.getDocxHtml).mockResolvedValue("<p>Nội dung đã sửa</p>");
  render(
    <Harness
      job={{ ...JOB, output_format: "docx", layout_cache: { md: true, docx: true, docx_html: true } }}
    />,
  );
  const pane = await screen.findByTestId("preview-docx-frame");
  expect(api.getDocxHtml).toHaveBeenCalledWith("5");
  await waitFor(() =>
    expect(pane.querySelector(".ProseMirror")).toHaveTextContent("Nội dung đã sửa"),
  );
  expect(api.exportJob).not.toHaveBeenCalled();
  expect(mammoth.convertToHtml).not.toHaveBeenCalled();
  expect(screen.getByTestId("layout-badge")).toHaveTextContent("Layout đã lưu");
});

it("Plan M3: docx_html cache nhưng GET 404 (null) → fallback mammoth docx-layout", async () => {
  vi.mocked(api.getDocxHtml).mockResolvedValue(null);
  render(
    <Harness
      job={{ ...JOB, output_format: "docx", layout_cache: { md: true, docx: true, docx_html: true } }}
    />,
  );
  await screen.findByTestId("preview-docx-frame");
  expect(api.getDocxHtml).toHaveBeenCalledWith("5");
  expect(api.exportJob).toHaveBeenCalledWith("5", "docx-layout");
  expect(mammoth.convertToHtml).toHaveBeenCalled();
});

it("Plan M3 → M5: md mode không còn MdToolbar/textarea hand-rolled (R51 exception theo lệnh dùng thư viện)", async () => {
  render(<Harness job={JOB} />);
  await screen.findByTestId("md-editor");
  expect(screen.queryByRole("toolbar", { name: "Công cụ Markdown" })).toBeNull();
  expect(screen.queryByTestId("textarea-markdown")).toBeNull();
  expect(screen.queryByTestId("btn-edit-source")).toBeNull();
});
