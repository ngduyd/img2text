import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

function previewUi(
  job: Job,
  fmt: "md-layout" | "docx-layout",
  onFmtChange: (f: "md-layout" | "docx-layout") => void = () => {},
): ReactElement {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={queryClient}>
      <LayoutPreview job={job} fmt={fmt} onFmtChange={onFmtChange} />
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
  renderPreview({ ...JOB, output_format: "docx", layout_cache: { md: true, docx: true, docx_html: true } }, "docx-layout");
  // fmt="docx-layout" (review r1 P0: controlled prop, không còn internal state) → word mode.
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

it("switch mode md → word (onFmtChange → rerender) renders preview-word", async () => {
  vi.mocked(api.exportJob).mockResolvedValue({ url: "" });
  vi.mocked(api.downloadExport).mockResolvedValue(new Blob(["# A"]));
  vi.mocked(api.getDocxHtml).mockResolvedValue("<p>B</p>");
  let currentFmt: "md-layout" | "docx-layout" = "md-layout";
  const onFmtChange = (f: "md-layout" | "docx-layout") => {
    currentFmt = f;
  };
  const { rerender } = render(previewUi(JOB, currentFmt, onFmtChange));
  await screen.findByTestId("preview-md");
  const user = userEvent.setup();
  await user.click(screen.getByTestId("preview-mode-word"));
  rerender(previewUi(JOB, currentFmt, onFmtChange));
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
