import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { User } from "../api/types";
import Admin from "./Admin";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
      adminListUsers: vi.fn(),
      adminPatchUser: vi.fn(),
      adminStats: vi.fn(),
      adminLogs: vi.fn(),
      adminLogsTail: vi.fn(),
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

it("tabs exist and users tab toggles ocr", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "admin", ocr_enabled: true } as User);
  vi.mocked(api.adminListUsers).mockResolvedValue({
    items: [{ id: 2, email: "a@x.io", role: "user", ocr_enabled: false, created_at: "2026-10-04" } as User],
    total: 1,
  });
  vi.mocked(api.adminPatchUser).mockResolvedValue({
    id: 2,
    email: "a@x.io",
    role: "user",
    ocr_enabled: true,
    created_at: "2026-10-04",
  } as User);
  renderWithRouter(<Admin />, { route: "/admin" });
  expect(screen.getByTestId("tab-users")).toBeInTheDocument();
  expect(screen.getByTestId("tab-stats")).toBeInTheDocument();
  expect(screen.getByTestId("tab-logs")).toBeInTheDocument();
  const user = userEvent.setup();
  const toggle = await screen.findByTestId("toggle-ocr-2");
  await user.click(toggle);
  expect(api.adminPatchUser).toHaveBeenCalledWith(2, { ocr_enabled: true });
});

it("stats tab renders cost column", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "admin", ocr_enabled: true } as User);
  vi.mocked(api.adminListUsers).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(api.adminStats).mockResolvedValue({
    days: [
      {
        date: "2026-10-04",
        users_registered: 1,
        jobs_submitted: 2,
        jobs_done: 1,
        jobs_failed: 1,
        page_views: 9,
        gpu_seconds: 10800,
        estimated_cost_usd: 7.5,
      },
    ],
  });
  renderWithRouter(<Admin />);
  const user = userEvent.setup();
  await user.click(screen.getByTestId("tab-stats"));
  expect(await screen.findByText("Chi phí ước tính")).toBeInTheDocument();
  expect(screen.getByText("7.5")).toBeInTheDocument();
});

it("logs tab filters by ip", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "admin", ocr_enabled: true } as User);
  vi.mocked(api.adminListUsers).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(api.adminLogs).mockResolvedValue({
    items: [
      {
        id: 1,
        ts: "2026-10-04T00:00:00Z",
        method: "POST",
        path: "/api/auth/login",
        status: 401,
        user_id: null,
        ip: "10.0.0.1",
        ua: "x",
      },
    ],
  });
  vi.mocked(api.adminLogsTail).mockResolvedValue({ lines: ["log line"] });
  renderWithRouter(<Admin />);
  const user = userEvent.setup();
  await user.click(screen.getByTestId("tab-logs"));
  await user.type(screen.getByTestId("input-log-ip"), "10.0.0.1");
  await user.click(screen.getByTestId("btn-logs-refresh"));
  await waitFor(() => expect(api.adminLogs).toHaveBeenCalledWith(expect.objectContaining({ ip: "10.0.0.1" })));
});

it("non-admin is redirected away", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  renderWithRouter(<Admin />, { route: "/admin" });
  await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith("/"));
  expect(screen.queryByTestId("tab-users")).not.toBeInTheDocument();
});
