import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../src/api/client";
import type { RegionOut } from "../../src/api/types";
import IssuesPanel from "../../src/components/IssuesPanel";

vi.mock("../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      getCropUrl: vi.fn(),
    },
  };
});

const regions: RegionOut[] = [
  { id: "p1r0", bbox: [1, 2, 3, 4], text: "", verdict: "image_unextractable", placeholder: true },
  { id: "p1r1", bbox: null, text: "", verdict: "unreadable", placeholder: false },
  { id: "p1r2", bbox: [9, 9, 20, 20], text: "ok text", verdict: "ok", placeholder: false },
];

/** Provider wraps like the App shell (R30). */
function renderPanel(): ReturnType<typeof render> {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const ui: ReactElement = (
    <QueryClientProvider client={queryClient}>
      <IssuesPanel jobId="5" regions={regions} />
    </QueryClientProvider>
  );
  return render(ui);
}

beforeEach(() => {
  vi.clearAllMocks();
});

it("renders only non-ok issues with vietnamese labels", async () => {
  vi.mocked(api.getCropUrl).mockResolvedValue({ url: "https://r2/crops/p1r0.jpg" });
  renderPanel();
  expect(await screen.findByTestId("issue-p1r0")).toBeInTheDocument();
  expect(screen.getByTestId("issue-p1r1")).toBeInTheDocument();
  expect(screen.queryByTestId("issue-p1r2")).toBeNull();
  expect(screen.getByTestId("issue-p1r0")).toHaveTextContent("Hình ảnh chưa trích xuất");
  expect(screen.getByTestId("issue-p1r1")).toHaveTextContent("Không trích xuất được văn bản");
});

it("shows crop image only when bbox present", async () => {
  vi.mocked(api.getCropUrl).mockResolvedValue({ url: "https://r2/crops/p1r0.jpg" });
  renderPanel();
  expect(((await screen.findByTestId("crop-p1r0")) as HTMLImageElement).src).toBe(
    "https://r2/crops/p1r0.jpg",
  );
  expect(screen.queryByTestId("crop-p1r1")).toBeNull();
});

/** JD2 accordion: rows luôn trong DOM, toggle issues-toggle → hiện (document-first). */
it("issues list collapsed by default and toggle reveals rows", async () => {
  vi.mocked(api.getCropUrl).mockResolvedValue({ url: "https://r2/crops/p1r0.jpg" });
  renderPanel();
  const toggle = await screen.findByTestId("issues-toggle");
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(screen.getByTestId("issues-list")).not.toBeVisible();
  expect(screen.getByTestId("issue-p1r0")).toBeInTheDocument();
  const user = userEvent.setup();
  await user.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByTestId("issues-list")).toBeVisible();
  expect(screen.getByTestId("btn-edit-region-p1r0")).toBeVisible();
});
