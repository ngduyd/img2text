import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../src/api/client";
import type { RegionOut, Suggestion } from "../../src/api/types";
import TextSection from "../../src/components/TextSection";

vi.mock("../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      getExtraction: vi.fn(),
      getSuggestions: vi.fn(),
      saveExtraction: vi.fn(),
      rejectSuggestion: vi.fn(),
      getCropUrl: vi.fn(),
    },
  };
});

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function renderSection(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

const SUGGESTION: Suggestion = {
  id: 11,
  page_index: 0,
  start: 4,
  end: 9,
  original: "chao",
  suggestion: "chào",
  reason: "thiếu dấu",
  status: "pending",
};

const REGIONS: RegionOut[] = [
  { id: "p1r0", bbox: [1, 2, 3, 4], text: "", verdict: "image_unextractable", placeholder: true },
];

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.getExtraction).mockResolvedValue({
    text: "Xin chao ban",
    text_version: 3,
  });
  vi.mocked(api.getSuggestions).mockResolvedValue([SUGGESTION]);
  vi.mocked(api.getCropUrl).mockResolvedValue({ url: "https://r2/c.jpg" });
});

it("renders issues panel below text when regions provided", async () => {
  renderSection(<TextSection jobId="5" regions={REGIONS} fileType="image" />);
  expect(await screen.findByTestId("extraction-text")).toBeInTheDocument();
  expect(screen.getByTestId("issues-toggle")).toBeInTheDocument();
});

it("no regions (extraction page) → no issues panel", async () => {
  renderSection(<TextSection jobId="5" />);
  expect(await screen.findByTestId("extraction-text")).toBeInTheDocument();
  expect(screen.queryByTestId("issues-toggle")).toBeNull();
});

it("Sửa khác… custom input → saveExtraction with custom phrase", async () => {
  const user = userEvent.setup();
  vi.mocked(api.saveExtraction).mockResolvedValue({
    synced: { md: true, docx: true },
    needs_render: [],
    text_version: 4,
    requires_rerender: false,
  });
  renderSection(<TextSection jobId="5" />);
  await user.click(within(await screen.findByTestId("suggestion-mark-11")).getByRole("button"));
  const input = screen.getByTestId("input-custom-11") as HTMLInputElement;
  await user.type(input, "xin chào");
  await user.click(screen.getByTestId("btn-save-custom-11"));
  await waitFor(() => expect(api.saveExtraction).toHaveBeenCalledTimes(1));
  expect(vi.mocked(api.saveExtraction).mock.calls[0]).toEqual([
    "5",
    {
      text: "Xin xin chào ban",
      old_phrase: "chao",
      new_phrase: "xin chào",
      expected_text_version: 3,
    },
  ]);
});

it("empty custom text → save button disabled", async () => {
  renderSection(<TextSection jobId="5" />);
  await screen.findByTestId("suggestion-mark-11");
  const user = userEvent.setup();
  await user.click(within(screen.getByTestId("suggestion-mark-11")).getByRole("button"));
  expect(screen.getByTestId("btn-save-custom-11")).toBeDisabled();
});

// --- Task 6: confirm modal queue (requires_rerender → "Lưu & xếp hàng") ---

it("save with requires_rerender → confirm modal; Lưu & xếp hàng → toast + invalidate", async () => {
  const user = userEvent.setup();
  vi.mocked(api.saveExtraction).mockResolvedValue({
    synced: { md: true, docx: true },
    needs_render: [],
    text_version: 4,
    requires_rerender: true,
  });
  const { toast } = await import("sonner");
  const { QueryClient, QueryClientProvider } = await import("@tanstack/react-query");
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const spy = vi.spyOn(queryClient, "invalidateQueries");
  render(
    <QueryClientProvider client={queryClient}>
      <TextSection jobId="5" />
    </QueryClientProvider>,
  );
  await user.click(within(await screen.findByTestId("suggestion-mark-11")).getByRole("button"));
  await user.click(screen.getByTestId("btn-apply-11"));
  const modal = await screen.findByTestId("rerender-modal");
  expect(modal).toHaveTextContent("Lưu văn bản sẽ cần vẽ lại layout. Thêm vào hàng đợi vẽ layout?");
  await user.click(screen.getByTestId("btn-rerender-confirm"));
  await waitFor(() =>
    expect(toast.success).toHaveBeenCalledWith("Đã xếp hàng vẽ lại layout."),
  );
  await waitFor(() =>
    expect(spy).toHaveBeenCalledWith({ queryKey: ["job", "5"] }),
  );
  expect(screen.queryByTestId("rerender-modal")).not.toBeInTheDocument();
});

it("requires_rerender modal: Hủy closes without queue toast", async () => {
  const user = userEvent.setup();
  vi.mocked(api.saveExtraction).mockResolvedValue({
    synced: { md: true, docx: true },
    needs_render: [],
    text_version: 4,
    requires_rerender: true,
  });
  const { toast } = await import("sonner");
  renderSection(<TextSection jobId="5" />);
  await user.click(within(await screen.findByTestId("suggestion-mark-11")).getByRole("button"));
  await user.click(screen.getByTestId("btn-apply-11"));
  await user.click(await screen.findByTestId("btn-rerender-cancel"));
  expect(screen.queryByTestId("rerender-modal")).not.toBeInTheDocument();
  expect(toast.success).not.toHaveBeenCalledWith("Đã xếp hàng vẽ lại layout.");
});
