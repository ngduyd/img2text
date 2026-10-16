import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { ApiError, api } from "../../src/api/client";
import MarkdownEditor from "../../src/components/MarkdownEditor";

vi.mock("../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      patchContent: vi.fn(),
    },
  };
});

let queryClient: QueryClient;

/** Provider wraps like the App shell (R30). */
function renderEditor(ui: ReactElement) {
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
});

it("edit toggles textarea and save calls patchContent", async () => {
  vi.mocked(api.patchContent).mockResolvedValue({});
  renderEditor(<MarkdownEditor jobId="5" initial={"## Part 2"} />);
  expect(screen.queryByTestId("textarea-markdown")).toBeNull();
  const user = userEvent.setup();
  await user.click(screen.getByTestId("btn-edit"));
  const ta = screen.getByTestId("textarea-markdown") as HTMLTextAreaElement;
  expect(ta.value).toBe("## Part 2");
  await user.clear(ta);
  await user.type(ta, "# Đã sửa");
  await user.click(screen.getByTestId("btn-save"));
  expect(api.patchContent).toHaveBeenCalledWith("5", "# Đã sửa");
  await waitFor(() => expect(screen.queryByTestId("textarea-markdown")).toBeNull());
});

it("shows ApiError detail on save failure and keeps edit open", async () => {
  vi.mocked(api.patchContent).mockRejectedValue(new ApiError("Nội dung quá lớn."));
  renderEditor(<MarkdownEditor jobId="5" initial={"## Part 2"} />);
  const user = userEvent.setup();
  await user.click(screen.getByTestId("btn-edit"));
  await user.click(screen.getByTestId("btn-save"));
  expect(await screen.findByTestId("editor-error")).toHaveTextContent(
    "Nội dung quá lớn.",
  );
  // Edit NOT lost on error: textarea stays open with typed content.
  expect(screen.getByTestId("textarea-markdown")).toHaveValue("## Part 2");
});

it("successful save invalidates job query (binding, T5 ledger)", async () => {
  vi.mocked(api.patchContent).mockResolvedValue({});
  renderEditor(<MarkdownEditor jobId="5" initial={"## Part 2"} />);
  const spy = vi.spyOn(queryClient, "invalidateQueries");
  const user = userEvent.setup();
  await user.click(screen.getByTestId("btn-edit"));
  await user.click(screen.getByTestId("btn-save"));
  await waitFor(() =>
    expect(spy).toHaveBeenCalledWith({ queryKey: ["job", "5"] }),
  );
});
