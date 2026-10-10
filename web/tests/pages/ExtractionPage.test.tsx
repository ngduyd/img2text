import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../src/api/client";
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
});

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
