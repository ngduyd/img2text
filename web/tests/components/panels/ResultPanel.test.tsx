import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { expect, it, vi } from "vitest";
import { api } from "../../../src/api/client";
import type { Job, RegionOut, ResultBody } from "../../../src/api/types";
import ResultPanel from "../../../src/components/panels/ResultPanel";

vi.mock("../../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../src/api/client")>();
  return {
    ...actual,
    api: { ...actual.api, exportJob: vi.fn(), downloadExport: vi.fn() },
  };
});

const r = (id: string, verdict: RegionOut["verdict"], text = ""): RegionOut => ({
  id,
  bbox: null,
  text,
  verdict,
  placeholder: false,
});

const RESULT: ResultBody = {
  model_version: "m1",
  gpu_seconds: 1.5,
  warnings: [],
  markdown: "# A",
  edited_markdown: null,
  pages: [
    {
      index: 0,
      width: 10,
      height: 10,
      page_flag: "ok",
      markdown: "# A",
      regions: [
        r("a1", "ok"),
        r("a2", "ok"),
        r("a3", "image_unextractable"),
        r("a4", "unreadable"),
        r("a5", "low_confidence"),
      ],
    },
    {
      index: 1,
      width: 10,
      height: 10,
      page_flag: "low_confidence",
      markdown: "# B",
      regions: [r("b1", "low_confidence")],
    },
  ],
};

const JOB: Job = {
  id: 5,
  status: "done",
  file_type: "pdf",
  page_count: 2,
  error: null,
  result: null,
  created_at: "2026-01-02T03:04:05Z",
  started_at: null,
  finished_at: null,
  output_format: "md",
  layout_cache: { md: false, docx: false },
  layout_style: null,
};

function renderPanel(result: ResultBody = RESULT): ReturnType<typeof render> {
  vi.mocked(api.exportJob).mockResolvedValue({ url: "" });
  vi.mocked(api.downloadExport).mockResolvedValue(new Blob(["# A"]));
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const ui: ReactElement = (
    <QueryClientProvider client={queryClient}>
      {/* JD2: editing/hostRef controlled by JobDetail — harness passes the controlled pair. */}
      <ResultPanel
        jobId="5"
        job={JOB}
        result={result}
        editing={false}
        onEditingChange={() => {}}
      />
    </QueryClientProvider>
  );
  return render(ui);
}

it("hosts unified editor + issues (Plan M gộp MarkdownEditor/PreviewTabs)", async () => {
  renderPanel();
  expect(screen.getByTestId("panel-result")).toBeInTheDocument();
  expect(await screen.findByTestId("panel-editor")).toBeInTheDocument();
  expect(await screen.findByTestId("preview-markdown")).toBeInTheDocument();
  expect(await screen.findByTestId("issue-a4")).toBeInTheDocument();
  // R51: các testid editor cũ (md-source-preview/md-edit-hint, btn-edit) gỡ theo Plan M
  expect(screen.queryByTestId("btn-edit")).toBeNull();
  expect(screen.queryByTestId("md-source-preview")).toBeNull();
  // JD2: accordion toggle present; rows stay in DOM (hidden until opened)
  expect(screen.getByTestId("issues-toggle")).toHaveAttribute("aria-expanded", "false");
  expect(screen.getByTestId("issues-list")).not.toBeVisible();
});
