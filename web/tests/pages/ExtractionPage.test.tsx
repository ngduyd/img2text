import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../src/api/client";
import type { Job, Suggestion } from "../../src/api/types";
import ExtractionPage from "../../src/pages/ExtractionPage";

vi.mock("../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      getExtraction: vi.fn(),
      getSuggestions: vi.fn(),
      saveExtraction: vi.fn(),
      retryLayout: vi.fn(),
      rejectSuggestion: vi.fn(),
      getJob: vi.fn(),
      getCropUrl: vi.fn(),
    },
  };
});

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

/** Route /jobs/5/extraction (R30 pattern); provider wraps like the App shell. */
function renderRoute(ui: ReactElement, route = "/jobs/5/extraction") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path="/jobs/:id/extraction" element={ui} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.getSuggestions).mockResolvedValue([]);
  // P2-3: trang trích xuất fetch job để thread file_type vào TextSection.
  vi.mocked(api.getJob).mockResolvedValue(PDF_JOB);
});

const TEXT = "Xin chao ban, chao nhe";

/** P2-3: PDF job → file_type phải được thread xuống TextSection (crop bị disable). */
const PDF_JOB = {
  id: 5,
  status: "done",
  file_type: "pdf",
  page_count: 2,
  error: null,
  result: null,
  created_at: "2026-01-02T03:04:05Z",
  started_at: null,
  finished_at: null,
  text_version: 3,
} as Job;

function pendingSuggestion(over: Partial<Suggestion>): Suggestion {
  return {
    id: 11,
    page_index: 0,
    start: 4,
    end: 9,
    original: "chao",
    suggestion: "chào",
    reason: "thiếu dấu",
    status: "pending",
    ...over,
  };
}

function renderWithSuggestions(items: Suggestion[]) {
  vi.mocked(api.getExtraction).mockResolvedValue({ text: TEXT, text_version: 3 });
  vi.mocked(api.getSuggestions).mockResolvedValue(items);
  renderRoute(<ExtractionPage />);
}

it("renders extraction text from API + back link to job detail", async () => {
  vi.mocked(api.getExtraction).mockResolvedValue({ text: "Đoạn văn gốc", text_version: 2 });
  renderRoute(<ExtractionPage />);
  expect(await screen.findByText("Đoạn văn gốc")).toBeInTheDocument();
  const back = screen.getByTestId("link-back-job");
  expect(back).toHaveAttribute("href", "/jobs/5");
});

it("shows skeleton while loading", () => {
  vi.mocked(api.getExtraction).mockReturnValue(new Promise(() => {}));
  renderRoute(<ExtractionPage />);
  expect(screen.getByTestId("extraction-loading")).toBeInTheDocument();
});

it("shows error state when extraction fetch fails", async () => {
  vi.mocked(api.getExtraction).mockRejectedValue(new Error("boom"));
  renderRoute(<ExtractionPage />);
  expect(await screen.findByTestId("extraction-error")).toBeInTheDocument();
});

// --- Task 3: highlight + popover + accept (save-sync) ---

it("marks pending suggestion phrases in the text", async () => {
  renderWithSuggestions([pendingSuggestion({})]);
  const mark = await screen.findByTestId("suggestion-mark-11");
  expect(mark).toHaveTextContent("chao");
  // cả 2 occurrence đều được mark
  expect(screen.getByTestId("suggestion-mark-11-1")).toBeInTheDocument();
});

it("clicking mark opens popover with Áp dụng / Bỏ qua", async () => {
  const user = userEvent.setup();
  renderWithSuggestions([pendingSuggestion({})]);
  await user.click(within(await screen.findByTestId("suggestion-mark-11")).getByRole("button"));
  const popover = screen.getByTestId("suggestion-popover-11");
  expect(within(popover).getByText("thiếu dấu")).toBeInTheDocument();
  expect(within(popover).getByTestId("btn-apply-11")).toBeInTheDocument();
  expect(within(popover).getByTestId("btn-reject-11")).toBeInTheDocument();
});

it("Áp dụng calls saveExtraction with replaced text + expected_text_version + invalidates", async () => {
  const user = userEvent.setup();
  vi.mocked(api.saveExtraction).mockResolvedValue({
    synced: { md: true, docx: true },
    needs_render: [],
    text_version: 4,
  });
  renderWithSuggestions([pendingSuggestion({})]);
  await user.click(within(await screen.findByTestId("suggestion-mark-11")).getByRole("button"));
  await user.click(screen.getByTestId("btn-apply-11"));
  await waitFor(() => expect(api.saveExtraction).toHaveBeenCalledTimes(1));
  expect(vi.mocked(api.saveExtraction).mock.calls[0]).toEqual([
    "5",
    {
      text: "Xin chào ban, chào nhe",
      old_phrase: "chao",
      new_phrase: "chào",
      expected_text_version: 3,
    },
  ]);
  await waitFor(() => expect(api.getExtraction).toHaveBeenCalledTimes(2)); // invalidate → refetch
});

it("409 conflict → toast error + refetch extraction (refresh optimistic lock)", async () => {
  const user = userEvent.setup();
  const { ApiError } = await import("../../src/api/client");
  const { toast } = await import("sonner");
  vi.mocked(api.saveExtraction).mockRejectedValue(
    new ApiError("Nội dung đã thay đổi ở nơi khác. Tải lại trang."),
  );
  renderWithSuggestions([pendingSuggestion({})]);
  await user.click(within(await screen.findByTestId("suggestion-mark-11")).getByRole("button"));
  await user.click(screen.getByTestId("btn-apply-11"));
  await waitFor(() => expect(toast.error).toHaveBeenCalled());
  await waitFor(() => expect(api.getExtraction).toHaveBeenCalledTimes(2));
});

it("Bỏ qua calls rejectSuggestion + refreshes suggestions", async () => {
  const user = userEvent.setup();
  vi.mocked(api.rejectSuggestion).mockResolvedValue({ status: "rejected" });
  renderWithSuggestions([pendingSuggestion({})]);
  await user.click(within(await screen.findByTestId("suggestion-mark-11")).getByRole("button"));
  await user.click(screen.getByTestId("btn-reject-11"));
  await waitFor(() => expect(api.rejectSuggestion).toHaveBeenCalledWith("5", 11));
});

// --- Task 4: needs_render hint + "Vẽ lại layout" ---

it("save result with needs_render → hint + btn-redraw-layout; redraw calls retryLayout", async () => {
  const user = userEvent.setup();
  vi.mocked(api.saveExtraction).mockResolvedValue({
    synced: { md: true, docx: false },
    needs_render: ["docx-layout"],
    text_version: 4,
  });
  vi.mocked(api.retryLayout).mockResolvedValue({ md: true, docx: true });
  renderWithSuggestions([pendingSuggestion({})]);
  await user.click(within(await screen.findByTestId("suggestion-mark-11")).getByRole("button"));
  await user.click(screen.getByTestId("btn-apply-11"));
  expect(await screen.findByTestId("needs-render-hint")).toBeInTheDocument();
  await user.click(screen.getByTestId("btn-redraw-layout"));
  await waitFor(() => expect(api.retryLayout).toHaveBeenCalledWith("5"));
  await waitFor(() => expect(screen.queryByTestId("needs-render-hint")).not.toBeInTheDocument());
});

it("save fully synced → no needs-render hint", async () => {
  const user = userEvent.setup();
  vi.mocked(api.saveExtraction).mockResolvedValue({
    synced: { md: true, docx: true },
    needs_render: [],
    text_version: 4,
  });
  renderWithSuggestions([pendingSuggestion({})]);
  await user.click(within(await screen.findByTestId("suggestion-mark-11")).getByRole("button"));
  await user.click(screen.getByTestId("btn-apply-11"));
  await waitFor(() => expect(api.saveExtraction).toHaveBeenCalled());
  expect(screen.queryByTestId("needs-render-hint")).not.toBeInTheDocument();
});

// --- Phase 2 review fixes: P1 repeat dead click, P2 detached confirm, P3 popover a11y ---

it("clicking repeat occurrence mark opens the same popover (P1 dead click)", async () => {
  const user = userEvent.setup();
  renderWithSuggestions([pendingSuggestion({})]);
  const repeat = await screen.findByTestId("suggestion-mark-11-1");
  await user.click(within(repeat).getByRole("button"));
  expect(screen.getByTestId("suggestion-popover-11")).toBeInTheDocument();
});

it("409 detached conflict → confirm dialog; confirmed → resend with force=true", async () => {
  const user = userEvent.setup();
  const { ApiError } = await import("../../src/api/client");
  vi.mocked(api.saveExtraction)
    .mockRejectedValueOnce(new ApiError("Layout có chỉnh tay. Đồng bộ sẽ ghi đè."))
    .mockResolvedValueOnce({ synced: { md: true, docx: true }, needs_render: [], text_version: 4 });
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
  renderWithSuggestions([pendingSuggestion({})]);
  await user.click(within(await screen.findByTestId("suggestion-mark-11")).getByRole("button"));
  await user.click(screen.getByTestId("btn-apply-11"));
  expect(confirmSpy).toHaveBeenCalledWith("Layout có chỉnh tay. Đồng bộ sẽ ghi đè. Tiếp tục?");
  await waitFor(() => expect(api.saveExtraction).toHaveBeenCalledTimes(2));
  expect(vi.mocked(api.saveExtraction).mock.calls[1][1]).toMatchObject({ force: true });
  confirmSpy.mockRestore();
});

it("409 detached conflict → user cancels confirm → no force resend", async () => {
  const user = userEvent.setup();
  const { ApiError } = await import("../../src/api/client");
  const { toast } = await import("sonner");
  vi.mocked(api.saveExtraction).mockRejectedValue(
    new ApiError("Layout có chỉnh tay. Đồng bộ sẽ ghi đè."),
  );
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
  renderWithSuggestions([pendingSuggestion({})]);
  await user.click(within(await screen.findByTestId("suggestion-mark-11")).getByRole("button"));
  await user.click(screen.getByTestId("btn-apply-11"));
  await waitFor(() => expect(toast.error).toHaveBeenCalled());
  expect(api.saveExtraction).toHaveBeenCalledTimes(1);
  confirmSpy.mockRestore();
});

it("Escape closes the popover (a11y)", async () => {
  const user = userEvent.setup();
  renderWithSuggestions([pendingSuggestion({})]);
  await user.click(within(await screen.findByTestId("suggestion-mark-11")).getByRole("button"));
  expect(screen.getByTestId("suggestion-popover-11")).toBeInTheDocument();
  await user.keyboard("{Escape}");
  await waitFor(() =>
    expect(screen.queryByTestId("suggestion-popover-11")).not.toBeInTheDocument(),
  );
});

it("click outside closes the popover (a11y)", async () => {
  const user = userEvent.setup();
  renderWithSuggestions([pendingSuggestion({})]);
  await user.click(within(await screen.findByTestId("suggestion-mark-11")).getByRole("button"));
  expect(screen.getByTestId("suggestion-popover-11")).toBeInTheDocument();
  await user.click(document.querySelector("h1")!);
  await waitFor(() =>
    expect(screen.queryByTestId("suggestion-popover-11")).not.toBeInTheDocument(),
  );
});

it("popover non-overflow: anchor giữa viewport → left-0 (không flip)", async () => {
  // P2: jsdom default 1024 là implicit — set rõ để test không phụ thuộc environment.
  const widthSpy = vi.spyOn(window, "innerWidth", "get").mockReturnValue(800);
  const user = userEvent.setup();
  const spy = vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue({
    x: 0, y: 0, top: 0, left: 100, right: 410, bottom: 0, width: 310, height: 20,
    toJSON: () => ({}),
  } as DOMRect);
  renderWithSuggestions([pendingSuggestion({})]);
  await user.click(within(await screen.findByTestId("suggestion-mark-11")).getByRole("button"));
  const pop = screen.getByTestId("suggestion-popover-11");
  expect(pop.className).toContain("left-0");
  expect(pop.className).not.toContain("right-0");
  spy.mockRestore();
  widthSpy.mockRestore();
});

it("popover flip: anchor sát mép phải viewport → right-0 + max-w (không tràn)", async () => {
  // P2: set innerWidth rõ ràng (bỏ phụ thuộc default 1024 của jsdom).
  const widthSpy = vi.spyOn(window, "innerWidth", "get").mockReturnValue(800);
  const user = userEvent.setup();
  const spy = vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue({
    x: 0, y: 0, top: 0, left: 700, right: 1010, bottom: 0, width: 310, height: 20,
    toJSON: () => ({}),
  } as DOMRect);
  renderWithSuggestions([pendingSuggestion({})]);
  await user.click(within(await screen.findByTestId("suggestion-mark-11")).getByRole("button"));
  const pop = screen.getByTestId("suggestion-popover-11");
  expect(pop.className).toContain("right-0 left-auto");
  expect(pop.className).toContain("max-w-[calc(100vw-2rem)]");
  spy.mockRestore();
  widthSpy.mockRestore();
});

/** P2: resize/scroll while open → popover phải recompute vị trí (không stale rect). */
it("popover recompute position on resize while open (không stale)", async () => {
  const widthSpy = vi.spyOn(window, "innerWidth", "get").mockReturnValue(800);
  const user = userEvent.setup();
  // Anchor giữa viewport → render left-0.
  const spy = vi.spyOn(Element.prototype, "getBoundingClientRect").mockReturnValue({
    x: 0, y: 0, top: 0, left: 100, right: 410, bottom: 0, width: 310, height: 20,
    toJSON: () => ({}),
  } as DOMRect);
  renderWithSuggestions([pendingSuggestion({})]);
  await user.click(within(await screen.findByTestId("suggestion-mark-11")).getByRole("button"));
  const pop = screen.getByTestId("suggestion-popover-11");
  expect(pop.className).toContain("left-0");
  // Resize: anchor giờ sát mép phải → phải flip sang right-0.
  spy.mockReturnValue({
    x: 0, y: 0, top: 0, left: 700, right: 760, bottom: 0, width: 60, height: 20,
    toJSON: () => ({}),
  } as DOMRect);
  fireEvent(window, new Event("resize"));
  await waitFor(() =>
    expect(screen.getByTestId("suggestion-popover-11").className).toContain("right-0"),
  );
  spy.mockRestore();
  widthSpy.mockRestore();
});

// --- P2-3 review r1: route extraction thread job.file_type (PDF → không crop fetch) ---

it("PDF job trên route extraction → fetch job + không gọi getCropUrl", async () => {
  vi.mocked(api.getExtraction).mockResolvedValue({ text: TEXT, text_version: 3 });
  renderRoute(<ExtractionPage />);
  expect(await screen.findByTestId("extraction-text")).toBeInTheDocument();
  expect(api.getJob).toHaveBeenCalledWith("5");
  expect(api.getCropUrl).not.toHaveBeenCalled();
});
