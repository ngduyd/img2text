import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { expect, it } from "vitest";
import type { RegionOut, ResultBody } from "../../api/types";
import ResultPanel from "./ResultPanel";

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
      <ResultPanel jobId="5" result={result} />
    </QueryClientProvider>
  );
  return render(ui);
}

it("stats line counts verdicts exactly across pages", () => {
  renderPanel();
  expect(screen.getByTestId("result-stats")).toHaveTextContent(
    "Tổng 6 vùng · 2 ok · 1 hình ảnh · 1 không trích xuất · 2 cần kiểm tra",
  );
});

it("hosts preview, issues, export + markdown editor", async () => {
  renderPanel();
  expect(screen.getByTestId("panel-result")).toBeInTheDocument();
  expect(screen.getByTestId("preview-markdown")).toBeInTheDocument();
  expect(await screen.findByTestId("issue-a4")).toBeInTheDocument();
  expect(screen.getByTestId("export-md")).toBeInTheDocument();
  expect(screen.getByTestId("btn-edit")).toBeInTheDocument();
});
