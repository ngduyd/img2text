import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { ApiError, api } from "../api/client";
import type { RegionOut } from "../api/types";
import IssuesPanel from "./IssuesPanel";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      getCropUrl: vi.fn(),
      patchRegion: vi.fn(),
    },
  };
});

const region: RegionOut = {
  id: "p1r0",
  bbox: [1, 2, 3, 4],
  text: "gốc",
  verdict: "low_confidence",
  placeholder: false,
};

/** RegionEditor is exercised through its host (IssuesPanel rows), per Task 2. */
function renderPanel(onRegionUpdated?: (rid: string, text: string) => void) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const ui: ReactElement = (
    <QueryClientProvider client={queryClient}>
      <IssuesPanel jobId="5" regions={[region]} onRegionUpdated={onRegionUpdated} />
    </QueryClientProvider>
  );
  const view = render(ui);
  return { ...view, queryClient };
}

async function openEditor() {
  const user = userEvent.setup();
  await user.click(await screen.findByTestId("btn-edit-region-p1r0"));
  return user;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.getCropUrl).mockResolvedValue({ url: "https://r2/c.jpg" });
});

it("save calls patchRegion with args, invalidates job, updates text, closes", async () => {
  vi.mocked(api.patchRegion).mockResolvedValue({ id: "p1r0", text: "mới", markdown_replaced: true });
  const onRegionUpdated = vi.fn();
  const { queryClient } = renderPanel(onRegionUpdated);
  const spy = vi.spyOn(queryClient, "invalidateQueries");
  const user = await openEditor();
  const ta = screen.getByTestId("textarea-region-p1r0") as HTMLTextAreaElement;
  expect(ta.value).toBe("gốc");
  await user.clear(ta);
  await user.type(ta, "mới");
  await user.click(screen.getByTestId("btn-save-region-p1r0"));
  await waitFor(() => expect(api.patchRegion).toHaveBeenCalledWith("5", "p1r0", "mới"));
  await waitFor(() => expect(spy).toHaveBeenCalledWith({ queryKey: ["job", "5"] }));
  expect(onRegionUpdated).toHaveBeenCalledWith("p1r0", "mới");
  expect(screen.getByTestId("issue-p1r0")).toHaveTextContent("mới");
  expect(screen.queryByTestId("textarea-region-p1r0")).toBeNull();
  expect(screen.queryByTestId("region-note-p1r0")).toBeNull();
});

it("markdown_replaced false shows inline replaced-note with exact text", async () => {
  vi.mocked(api.patchRegion).mockResolvedValue({
    id: "p1r0",
    text: "mới",
    markdown_replaced: false,
  });
  renderPanel();
  const user = await openEditor();
  await user.clear(screen.getByTestId("textarea-region-p1r0"));
  await user.type(screen.getByTestId("textarea-region-p1r0"), "mới");
  await user.click(screen.getByTestId("btn-save-region-p1r0"));
  expect((await screen.findByTestId("region-note-p1r0")).textContent).toBe(
    "Văn bản vùng đã cập nhật; markdown chưa thay thế (text gốc không còn trong bản xem trước)",
  );
});

it("cancel restores original value: reopen shows unedited text", async () => {
  vi.mocked(api.patchRegion).mockResolvedValue({ id: "p1r0", text: "x", markdown_replaced: true });
  renderPanel();
  let user = await openEditor();
  await user.clear(screen.getByTestId("textarea-region-p1r0"));
  await user.type(screen.getByTestId("textarea-region-p1r0"), "sai");
  await user.click(screen.getByTestId("btn-cancel-region-p1r0"));
  expect(screen.queryByTestId("textarea-region-p1r0")).toBeNull();
  expect(api.patchRegion).not.toHaveBeenCalled();
  user = await openEditor();
  expect((screen.getByTestId("textarea-region-p1r0") as HTMLTextAreaElement).value).toBe("gốc");
});

it("patchRegion 404 ApiError shows error text, editor stays open", async () => {
  vi.mocked(api.patchRegion).mockRejectedValue(new ApiError("Not Found."));
  renderPanel();
  const user = await openEditor();
  await user.click(screen.getByTestId("btn-save-region-p1r0"));
  expect(await screen.findByTestId("region-error-p1r0")).toHaveTextContent("Not Found.");
  expect(screen.getByTestId("textarea-region-p1r0")).toBeInTheDocument();
});
