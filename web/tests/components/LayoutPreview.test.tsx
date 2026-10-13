import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../src/api/client";
import { toast } from "sonner";
import type { Job } from "../../src/api/types";
import LayoutPreview from "../../src/components/LayoutPreview";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock("../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      exportJob: vi.fn(),
      downloadExport: vi.fn(),
      getDocxHtml: vi.fn(),
      patchLayoutContent: vi.fn(),
    },
  };
});

const JOB: Job = {
  id: 5,
  status: "done",
  file_type: "pdf",
  page_count: 2,
  output_format: "md",
  error: null,
  created_at: "2026-01-02T03:04:05Z",
  started_at: null,
  finished_at: null,
  result: null,
  text_version: 1,
  layout_style: { fontFamily: "Times New Roman", fontSize: 18 },
};

function renderPreview(job: Job = JOB, editing = false): ReturnType<typeof render> {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const ui: ReactElement = (
    <QueryClientProvider client={queryClient}>
      <LayoutPreview job={job} editing={editing} />
    </QueryClientProvider>
  );
  return render(ui);
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.getDocxHtml).mockResolvedValue(null);
});

/** WS-UI: md → HTML sanitize + docStyle (scope .layout-preview). */
it("md mode renders sanitized markdown + scoped docStyle", async () => {
  vi.mocked(api.exportJob).mockResolvedValue({ url: "" });
  vi.mocked(api.downloadExport).mockResolvedValue(
    new Blob(["# Tieu de\n\n**manh** <script>alert(1)</script>"]),
  );
  renderPreview();
  const pane = await screen.findByTestId("preview-md");
  expect(api.exportJob).toHaveBeenCalledWith(5, "md-layout");
  expect(pane.querySelector("h1")?.textContent).toBe("Tieu de");
  expect(pane.querySelector("strong")?.textContent).toBe("manh");
  // DOMPurify strip script; style block scope .layout-preview (rule body → container).
  expect(pane.querySelector("script")).toBeNull();
  expect(pane.querySelector("style")?.textContent).toContain(".layout-preview");
  expect(pane.querySelector("style")?.textContent).toContain("Times New Roman");
  // Lane B Task 2: base doc style luôn có (Inter stack, prose 65ch, accent) — không khối chữ trần.
  const css = pane.querySelector("style")?.textContent ?? "";
  expect(css).toContain("Inter");
  expect(css).toContain("65ch");
  expect(css).toContain("#2563eb");
});

/** WS-UI: word → iframe sandbox srcDoc = docStyle + docx.html. */
it("word mode renders sandboxed iframe with docStyle in srcDoc", async () => {
  vi.mocked(api.getDocxHtml).mockResolvedValue("<p>Noi dung</p>");
  vi.mocked(api.exportJob).mockResolvedValue({ url: "" });
  vi.mocked(api.downloadExport).mockResolvedValue(new Blob(["<p>x</p>"]));
  renderPreview({ ...JOB, output_format: "docx", layout_cache: { md: true, docx: true, docx_html: true } });
  // default mode theo output_format = word.
  const frame = await screen.findByTestId("preview-word");
  expect(frame).toHaveAttribute("sandbox", "");
  const src = frame.getAttribute("srcdoc") ?? "";
  expect(src).toContain("Noi dung");
  expect(src).toContain("font-size: 18px");
  // Lane B Task 2: base doc style trong srcDoc của word pane.
  expect(src).toContain("65ch");
  expect(src).toContain("#2563eb");
  expect(api.getDocxHtml).toHaveBeenCalledWith(5);
});

it("switch mode md → word renders preview-word", async () => {
  vi.mocked(api.exportJob).mockResolvedValue({ url: "" });
  vi.mocked(api.downloadExport).mockResolvedValue(new Blob(["# A"]));
  vi.mocked(api.getDocxHtml).mockResolvedValue("<p>B</p>");
  renderPreview();
  await screen.findByTestId("preview-md");
  const user = userEvent.setup();
  await user.click(screen.getByTestId("preview-mode-word"));
  await waitFor(() => expect(screen.getByTestId("preview-word")).toBeInTheDocument());
  expect(screen.getByTestId("preview-mode-word")).toHaveAttribute("aria-pressed", "true");
});

it("export failure → role=alert error + retry button", async () => {
  vi.mocked(api.exportJob).mockRejectedValue(new Error("boom"));
  renderPreview();
  const alert = await screen.findByTestId("preview-error");
  expect(alert).toHaveAttribute("role", "alert");
  expect(screen.getByTestId("btn-retry-preview")).toBeInTheDocument();
});

/** Wave-3 #7: "Chỉnh sửa layout" → md pane = textarea; Lưu layout → PATCH + toast. */
it("editing → md pane = textarea (nguồn md-layout); save calls PATCH + toast", async () => {
  vi.mocked(api.exportJob).mockResolvedValue({ url: "" });
  vi.mocked(api.downloadExport).mockResolvedValue(new Blob(["# Ban dau"]));
  vi.mocked(api.patchLayoutContent).mockResolvedValue({ ok: true });
  renderPreview(JOB, true);
  const ta = await screen.findByTestId("layout-editor-textarea");
  expect(ta).toHaveValue("# Ban dau");
  // Preview HTML bị thay bằng editor khi editing (mặc định = xem).
  expect(screen.queryByTestId("preview-md")).not.toBeInTheDocument();
  const user = userEvent.setup();
  await user.clear(ta);
  await user.type(ta, "# Da sua");
  await user.click(screen.getByTestId("btn-save-layout-md"));
  await waitFor(() =>
    expect(api.patchLayoutContent).toHaveBeenCalledWith(5, "# Da sua"),
  );
  await waitFor(() =>
    expect(toast.success).toHaveBeenCalledWith("Đã lưu layout."),
  );
});

it("editing + word mode → word pane giữ nguyên preview (không textarea)", async () => {
  vi.mocked(api.getDocxHtml).mockResolvedValue("<p>Noi dung</p>");
  renderPreview({ ...JOB, output_format: "docx" }, true);
  expect(await screen.findByTestId("preview-word")).toBeInTheDocument();
  expect(screen.queryByTestId("layout-editor-textarea")).not.toBeInTheDocument();
});
