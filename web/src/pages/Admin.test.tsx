import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { ApiError } from "../api/client";
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

const adminMe = { id: 1, role: "admin", ocr_enabled: true } as User;

beforeEach(() => {
  vi.clearAllMocks();
});

it("renders 5 tabs, default overview with summed stat cards", async () => {
  vi.mocked(api.me).mockResolvedValue(adminMe);
  vi.mocked(api.adminStats).mockResolvedValue({
    days: [
      {
        date: "2026-10-03",
        users_registered: 2,
        jobs_submitted: 4,
        jobs_done: 3,
        jobs_failed: 1,
        page_views: 10,
        gpu_seconds: 100.5,
        estimated_cost_usd: 1.25,
      },
      {
        date: "2026-10-04",
        users_registered: 1,
        jobs_submitted: 3,
        jobs_done: 2,
        jobs_failed: 0,
        page_views: 5,
        gpu_seconds: 50,
        estimated_cost_usd: 2.5,
      },
    ],
  });
  renderWithRouter(<Admin />, { route: "/admin" });
  expect(screen.getByTestId("tab-overview")).toBeInTheDocument();
  expect(screen.getByTestId("tab-users")).toBeInTheDocument();
  expect(screen.getByTestId("tab-api")).toBeInTheDocument();
  expect(screen.getByTestId("tab-logs")).toBeInTheDocument();
  expect(screen.getByTestId("tab-stats")).toBeInTheDocument();
  // Default tab = overview; sums across days[] exact.
  const statUsers = await screen.findByTestId("stat-users");
  await waitFor(() => expect(within(statUsers).getByText("3")).toBeInTheDocument());
  expect(within(screen.getByTestId("stat-done")).getByText("5")).toBeInTheDocument();
  expect(within(screen.getByTestId("stat-failed")).getByText("1")).toBeInTheDocument();
  expect(within(screen.getByTestId("stat-gpu")).getByText("150.5")).toBeInTheDocument();
  expect(within(screen.getByTestId("stat-cost")).getByText("3.75")).toBeInTheDocument();
  // Card labels verbatim.
  expect(screen.getByText("User mới (7 ngày)")).toBeInTheDocument();
  expect(screen.getByText("Job hoàn tất")).toBeInTheDocument();
  expect(screen.getByText("Job thất bại")).toBeInTheDocument();
  expect(screen.getByText("Tổng GPU (giây)")).toBeInTheDocument();
  expect(screen.getByText("Chi phí ước tính (USD)")).toBeInTheDocument();
});

it("overview quick links navigate to other tabs", async () => {
  vi.mocked(api.me).mockResolvedValue(adminMe);
  vi.mocked(api.adminStats).mockResolvedValue({ days: [] });
  vi.mocked(api.adminListUsers).mockResolvedValue({ items: [], total: 0 });
  renderWithRouter(<Admin />);
  const user = userEvent.setup();
  await user.click(await screen.findByTestId("btn-goto-users"));
  // ui-ux redo: empty users list → empty state box (table hidden); tab mounted
  expect(await screen.findByText("Chưa có người dùng")).toBeInTheDocument();
  expect(screen.queryByTestId("stat-users")).not.toBeInTheDocument();
  await user.click(screen.getByTestId("tab-overview"));
  await user.click(await screen.findByTestId("btn-goto-api"));
  expect(screen.getByTestId("api-activity-table")).toBeInTheDocument();
});

it("api tab aggregates paths client-side, collapsing numeric segments", async () => {
  vi.mocked(api.me).mockResolvedValue(adminMe);
  vi.mocked(api.adminLogs).mockResolvedValue({
    items: [
      // SAME path, different methods → must collapse into ONE /api/jobs/{id} row
      { path: "/api/jobs/7", method: "GET", status: 200 },
      { path: "/api/jobs/7", method: "POST", status: 201 },
      { path: "/api/jobs/12", method: "PATCH", status: 200 },
      { path: "/api/jobs/13/regions/r1", method: "GET", status: 500 },
      { path: "/api/admin/users", method: "GET", status: 200 },
      { path: "/api/auth/login", method: "POST", status: 401 },
      // out-of-class status (1xx) → skipped, total stays honest
      { path: "/api/ping", method: "GET", status: 102 },
    ],
  });
  renderWithRouter(<Admin />);
  const user = userEvent.setup();
  await user.click(await screen.findByTestId("tab-api"));
  expect(api.adminLogs).toHaveBeenCalledWith({ limit: 500 });
  expect(
    screen.getByText("Tổng hợp client-side từ request_logs (500 dòng gần nhất)"),
  ).toBeInTheDocument();
  const table = screen.getByTestId("api-activity-table");
  // GET /api/jobs/7 + POST /api/jobs/7 + PATCH /api/jobs/12 + GET /api/jobs/13/regions/r1
  // → ONE path-only row /api/jobs/{id}, classes merged
  const jobsRow = within(table).getByTestId("api-row--api-jobs--id-");
  expect(within(jobsRow).getByText("/api/jobs/{id}")).toBeInTheDocument();
  expect(within(jobsRow).getByText("4")).toBeInTheDocument(); // total (merged across methods)
  expect(within(jobsRow).getByText("3")).toBeInTheDocument(); // 2xx
  expect(within(jobsRow).getByText("1")).toBeInTheDocument(); // 5xx
  expect(within(jobsRow).getByText("0")).toBeInTheDocument(); // 4xx
  // path-only grouping: no duplicate rows/testids for the same normalized path
  expect(table.querySelectorAll("[data-testid='api-row--api-jobs--id-']")).toHaveLength(1);
  expect(within(table).queryByTestId("api-row--api-ping")).not.toBeInTheDocument(); // 1xx skipped
  const usersRow = within(table).getByTestId("api-row--api-admin-users");
  // total=1, 2xx=1 → two "1"s
  expect(within(usersRow).getAllByText("1")).toHaveLength(2);
  const loginRow = within(table).getByTestId("api-row--api-auth-login");
  expect(within(loginRow).getByText("/api/auth/login")).toBeInTheDocument();
  // cells: total=1, 2xx=0, 4xx=1, 5xx=0 → two "1"s (total + 4xx)
  expect(within(loginRow).getAllByText("1")).toHaveLength(2);
  expect(within(loginRow).getAllByText("0")).toHaveLength(2);
});

it("users tab shows created_at and toggles ocr", async () => {
  vi.mocked(api.me).mockResolvedValue(adminMe);
  vi.mocked(api.adminListUsers).mockResolvedValue({
    items: [
      { id: 2, email: "a@x.io", role: "user", ocr_enabled: false, created_at: "2026-10-04T12:00:00Z" } as User,
    ],
    total: 1,
  });
  vi.mocked(api.adminPatchUser).mockResolvedValue({
    id: 2,
    email: "a@x.io",
    role: "user",
    ocr_enabled: true,
    created_at: "2026-10-04T12:00:00Z",
  } as User);
  renderWithRouter(<Admin />);
  const user = userEvent.setup();
  await user.click(await screen.findByTestId("tab-users"));
  expect(screen.getByText("Ngày tạo")).toBeInTheDocument();
  expect(screen.getByText(/0?4\/10\/2026/)).toBeInTheDocument();
  const toggle = await screen.findByTestId("toggle-ocr-2");
  // ui-ux redo: role badge tone + icon toggle exposes pressed state (a11y)
  expect(screen.getByTestId("role-badge-2")).toHaveAttribute("data-tone", "neutral");
  // Task 3: high-density rule — numeric ID column rendered mono (DESIGN.md §3)
  expect(screen.getByText("2")).toHaveClass("font-mono");
  expect(toggle).toHaveAttribute("aria-pressed", "false");
  await user.click(toggle);
  expect(api.adminPatchUser).toHaveBeenCalledWith(2, { ocr_enabled: true });
});

it("stats tab renders cost column", async () => {
  vi.mocked(api.me).mockResolvedValue(adminMe);
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
  vi.mocked(api.me).mockResolvedValue(adminMe);
  vi.mocked(api.adminListUsers).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(api.adminLogs).mockResolvedValue({
    items: [
      {
        id: 1,
        ts: "2026-10-04T00:00:00Z",
        method: "POST",
        path: "/api/auth/login",
        status: 401,
        user_id: null, // anonymous → actor cell renders "—"
        ip: "10.0.0.1",
        ua: "x",
      },
      {
        id: 2,
        ts: "2026-10-04T00:00:01Z",
        method: "GET",
        path: "/api/jobs",
        status: 200,
        user_id: 5,
        ip: "10.0.0.1",
        ua: "y",
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
  // Plan X R60: audit rows expose IP + User-Agent cells (truncate, title = full)
  const ipCells = await screen.findAllByTestId("audit-ip");
  expect(ipCells[0]).toHaveTextContent("10.0.0.1");
  expect(ipCells[0].firstChild).toHaveAttribute("title", "10.0.0.1");
  const uaCells = screen.getAllByTestId("audit-ua");
  expect(uaCells[0]).toHaveTextContent("x");
  expect(uaCells[0].firstChild).toHaveAttribute("title", "x");
  expect(screen.getByRole("columnheader", { name: "User-Agent" })).toBeInTheDocument();
  // R60a: actor column — user_id rendered, anonymous → em dash, title = full
  expect(screen.getByRole("columnheader", { name: "Người dùng" })).toBeInTheDocument();
  const actorCells = screen.getAllByTestId("audit-actor");
  expect(actorCells[0]).toHaveTextContent("—");
  expect(actorCells[0].firstChild).toHaveAttribute("title", "");
  expect(actorCells[1]).toHaveTextContent("5");
  expect(actorCells[1].firstChild).toHaveAttribute("title", "5");
  // Task 3 (DESIGN.md density 6): IP/actor IDs mono + status badge tone by class
  expect(ipCells[0].firstChild).toHaveClass("font-mono");
  expect(actorCells[1].firstChild).toHaveClass("font-mono");
  expect(screen.getByText("401")).toHaveAttribute("data-tone", "warning");
  expect(screen.getByText("200")).toHaveAttribute("data-tone", "success");
});

it("admin home has no jobs board, no dropzone (absence asserts)", async () => {
  vi.mocked(api.me).mockResolvedValue(adminMe);
  vi.mocked(api.adminStats).mockResolvedValue({ days: [] });
  renderWithRouter(<Admin />, { route: "/admin" });
  await screen.findByTestId("stat-users"); // admin content rendered
  expect(screen.queryAllByTestId((id: string) => id.startsWith("job-row"))).toHaveLength(0);
  expect(screen.queryByText(/Kéo thả file vào đây/)).not.toBeInTheDocument();
  expect(screen.queryByTestId("dropzone")).not.toBeInTheDocument();
});

it("admin sub-rail renders 5 items; active item has aria-current=page", async () => {
  vi.mocked(api.me).mockResolvedValue(adminMe);
  vi.mocked(api.adminStats).mockResolvedValue({ days: [] });
  renderWithRouter(<Admin />, { route: "/admin" });
  await screen.findByTestId("stat-users"); // admin content rendered
  const rail = screen.getByTestId("admin-rail");
  // V3: one responsive nav (mobile scroll / desktop vertical), 5 items with icons
  expect(within(rail).getAllByRole("button")).toHaveLength(5);
  expect(within(rail).getByTestId("tab-overview")).toHaveAttribute("aria-current", "page");
  expect(within(rail).getByTestId("tab-users")).not.toHaveAttribute("aria-current");
});

it("clicking rail users item mounts AdminUsers", async () => {
  vi.mocked(api.me).mockResolvedValue(adminMe);
  vi.mocked(api.adminListUsers).mockResolvedValue({ items: [], total: 0 });
  renderWithRouter(<Admin />);
  const user = userEvent.setup();
  await user.click(await screen.findByTestId("tab-users"));
  expect(await screen.findByText("Chưa có người dùng")).toBeInTheDocument();
});

it("non-admin is redirected away", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  renderWithRouter(<Admin />, { route: "/admin" });
  await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith("/"));
  expect(screen.queryByTestId("tab-users")).not.toBeInTheDocument();
});

it("me error redirects to /login and renders no tabs", async () => {
  vi.mocked(api.me).mockRejectedValue(new ApiError("Unauthorized."));
  renderWithRouter(<Admin />, { route: "/admin" });
  await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith("/login"));
  expect(screen.queryByTestId("tab-users")).not.toBeInTheDocument();
});
