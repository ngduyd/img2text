import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { expect, it } from "vitest";
import type { RegionOut, ResultBody } from "../../../src/api/types";
import ResultPanel from "../../../src/components/panels/ResultPanel";

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

function renderPanel(result: ResultBody = RESULT): ReturnType<typeof render> {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const ui: ReactElement = (
    <QueryClientProvider client={queryClient}>
      {/* JD2: editing/hostRef controlled by JobDetail — harness passes the controlled pair. */}
      <ResultPanel jobId="5" result={result} editing={false} onEditingChange={() => {}} />
    </QueryClientProvider>
  );
  return render(ui);
}

it("hosts preview, issues + markdown editor (stats/export moved to JobDetail rail)", async () => {
  renderPanel();
  expect(screen.getByTestId("panel-result")).toBeInTheDocument();
  expect(screen.getByTestId("preview-markdown")).toBeInTheDocument();
  expect(await screen.findByTestId("issue-a4")).toBeInTheDocument();
  // R51 exception (user "1 chỗ thôi"): editor panel has no btn-edit — preview + hint.
  expect(screen.queryByTestId("btn-edit")).toBeNull();
  expect(screen.getByTestId("md-source-preview")).toBeInTheDocument();
  expect(screen.getByTestId("md-edit-hint")).toBeInTheDocument();
  // JD2: accordion toggle present; rows stay in DOM (hidden until opened)
  expect(screen.getByTestId("issues-toggle")).toHaveAttribute("aria-expanded", "false");
  expect(screen.getByTestId("issues-list")).not.toBeVisible();
});
