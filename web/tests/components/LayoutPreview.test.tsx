import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../src/api/client";
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

function previewUi(job: Job, fmt: "md-layout" | "docx-layout"): ReactElement {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={queryClient}>
      <LayoutPreview job={job} fmt={fmt} />
    </QueryClientProvider>
  );
}

function renderPreview(
  job: Job = JOB,
  fmt: "md-layout" | "docx-layout" = "md-layout",
): ReturnType<typeof render> {
  return render(previewUi(job, fmt));
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
  // Lane B Task 2: base doc style luôn có (system-ui stack, prose 65ch, accent token) — không khối chữ trần.
  const css = pane.querySelector("style")?.textContent ?? "";
  expect(css).toContain("system-ui");
  expect(css).toContain("65ch");
  expect(css).toContain("var(--accent-text)");
});

/** WS-UI: word → iframe sandbox srcDoc = docStyle + docx.html. */
it("word mode renders sandboxed iframe with docStyle in srcDoc", async () => {
  vi.mocked(api.getDocxHtml).mockResolvedValue("<p>Noi dung</p>");
  vi.mocked(api.exportJob).mockResolvedValue({ url: "" });
  vi.mocked(api.downloadExport).mockResolvedValue(new Blob(["<p>x</p>"]));
  renderPreview({ ...JOB, output_format: "docx", layout_cache: { md: true, docx: true, docx_html: true } }, "docx-layout");
  // fmt="docx-layout" (review r1 P0: controlled prop, không còn internal state) → word mode.
  const frame = await screen.findByTestId("preview-word");
  expect(frame).toHaveAttribute("sandbox", "");
  const src = frame.getAttribute("srcdoc") ?? "";
  expect(src).toContain("Noi dung");
  expect(src).toContain("font-size: 18px");
  // Lane B Task 2: base doc style trong srcDoc của word pane.
  expect(src).toContain("65ch");
  expect(src).toContain("var(--accent-text)");
  // Iframe không inherit tokens → :root --accent-text cả 2 theme (light = #0861cf).
  expect(src).toContain("--accent-text: #58a6ff");
  expect(src).toContain("--accent-text: #0861cf");
  expect(api.getDocxHtml).toHaveBeenCalledWith(5);
});

/** U7: preview toggle MD/Word bị gỡ — không còn testid preview-mode-*. */
it("U7: no preview-mode-md/preview-mode-word toggle in DOM", async () => {
  vi.mocked(api.exportJob).mockResolvedValue({ url: "" });
  vi.mocked(api.downloadExport).mockResolvedValue(new Blob(["# A"]));
  renderPreview();
  await screen.findByTestId("preview-md");
  expect(screen.queryByTestId("preview-mode-md")).not.toBeInTheDocument();
  expect(screen.queryByTestId("preview-mode-word")).not.toBeInTheDocument();
});

it("export failure → role=alert error + retry button", async () => {
  vi.mocked(api.exportJob).mockRejectedValue(new Error("boom"));
  renderPreview();
  const alert = await screen.findByTestId("preview-error");
  expect(alert).toHaveAttribute("role", "alert");
  expect(screen.getByTestId("btn-retry-preview")).toBeInTheDocument();
});
