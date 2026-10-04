import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { Job, User } from "../api/types";
import Jobs from "./Jobs";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
      listJobs: vi.fn(),
      uploadJob: vi.fn(),
    },
  };
});

export const mockNavigate = vi.fn();

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

/** Page tests: MemoryRouter + QueryClientProvider (App wraps both in prod). */
function renderWithRouter(ui: ReactElement, { route = "/" } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(ui, {
    wrapper: ({ children }) => (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
      </QueryClientProvider>
    ),
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

it("banner and disabled upload when ocr_enabled false", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: false } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  renderWithRouter(<Jobs />);
  expect(await screen.findByTestId("banner-no-access")).toHaveTextContent("Chờ admin cấp quyền");
  expect(screen.getByTestId("btn-upload")).toBeDisabled();
});

it("upload button enabled and calls api when granted", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(api.uploadJob).mockResolvedValue({ id: 42, status: "queued", page_count: 3 } as Job);
  renderWithRouter(<Jobs />);
  const btn = await screen.findByTestId("btn-upload");
  expect(btn).toBeEnabled();
  const file = new File(["x"], "a.jpg", { type: "image/jpeg" });
  const user = userEvent.setup();
  await user.upload(screen.getByTestId("input-file"), file);
  expect(api.uploadJob).toHaveBeenCalledWith(file);
  await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith("/jobs/42"));
});

it("job rows render status badge", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({
    items: [
      {
        id: 7,
        status: "queued",
        page_count: 2,
        file_type: "pdf",
        created_at: "2026-10-04T00:00:00Z",
        error: null,
      } as Job,
    ],
    total: 1,
  });
  renderWithRouter(<Jobs />);
  expect(await screen.findByTestId("job-row-7")).toBeInTheDocument();
  expect(screen.getByTestId("badge-7")).toHaveTextContent("Chờ xử lý");
});
