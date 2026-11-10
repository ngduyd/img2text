import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as mammoth from "mammoth";
import { QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { ApiError, api } from "../src/api/client";
import type { Job, ResultBody, User } from "../src/api/types";
import App, { AuthZone, queryClient } from "../src/App";

vi.mock("../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../src/api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
      logout: vi.fn(),
      listJobs: vi.fn(),
      uploadJob: vi.fn(),
      // Lane B Task 4: AppNav mount QuotaBadge — mock null (ẩn) cho phần lớn test.
      getMyQuota: vi.fn(async () => null),
      // Lane 1 (layout route split): route-level tests render JobDetail thật ở
      // /jobs/:id/layout[/md|/word] — mock chuỗi export/preview của nó.
      getJob: vi.fn(),
      listVersions: vi.fn(async () => ({ items: [] })),
      downloadJobFile: vi.fn(),
      exportJob: vi.fn(),
      downloadExport: vi.fn(),
      getDocxHtml: vi.fn(),
      getLayoutPreviewHtml: vi.fn(),
    },
  };
});

// Word-mode preview/editor fallback đi qua mammoth khi không có layout_spec HTML.
vi.mock("mammoth", () => ({ convertToHtml: vi.fn() }));

export const mockNavigate = vi.fn();

// jsdom has no IntersectionObserver; Landing's Reveal (whileInView) mounts one.
class MockIntersectionObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
vi.stubGlobal("IntersectionObserver", MockIntersectionObserver);

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return {
    ...actual,
    // Wrap the real navigate: <Navigate/> redirects (e.g. /landing → /) must
    // still change the route, while mockNavigate keeps call-target assertions
    // working. Trailing-undefined args dropped so toHaveBeenCalledWith("/signin")
    // keeps matching single-arg calls.
    useNavigate: () => {
      const navigate = actual.useNavigate() as (to: unknown, opts?: unknown) => unknown;
      return ((to: unknown, opts?: unknown) => {
        if (opts === undefined) mockNavigate(to);
        else mockNavigate(to, opts);
        return navigate(to, opts);
      }) as typeof actual.useNavigate;
    },
  };
});

beforeEach(() => {
  vi.clearAllMocks();
  queryClient.clear();
  localStorage.clear();
  document.documentElement.classList.remove("dark");
  window.history.pushState({}, "", "/");
  // jsdom: Element.scrollIntoView không có (JobDetail editor effect dùng nó).
  (Element.prototype.scrollIntoView as unknown) = vi.fn();
});

it("renders app shell with brand and left nav links for logged-out", () => {
  render(<App />);
  expect(screen.getByTestId("nav-brand")).toHaveTextContent("img2text");
  const jobsLink = screen.getByTestId("nav-link-jobs");
  expect(jobsLink).toBeInTheDocument();
  // Root is landing now; the jobs nav-link points at the /jobs list route.
  expect(jobsLink).toHaveAttribute("href", "/jobs");
  // R51 (user instruction "bỏ cái word trên nav"): no word/edit nav entry at all.
  expect(screen.queryByTestId("nav-link-word")).not.toBeInTheDocument();
  expect(screen.queryByTestId("nav-link-edit")).not.toBeInTheDocument();
  // R51: admin link is role-gated (binding nav contract) — asserted in admin test.
  expect(screen.queryByTestId("nav-link-admin")).not.toBeInTheDocument();
});

it("/ renders Landing publicly (hero H1 + CTA to /signin)", async () => {
  vi.mocked(api.me).mockRejectedValue(new ApiError("Unauthorized."));
  render(<App />);
  expect(await screen.findByTestId("landing-hero")).toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
    "Turn photos and PDFs into editable text",
  );
  expect(screen.getByTestId("landing-cta")).toHaveAttribute("href", "/signin");
});

it("/jobs renders the Jobs list (empty-state)", async () => {
  vi.mocked(api.me).mockRejectedValue(new ApiError("Unauthorized."));
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  window.history.pushState({}, "", "/jobs");
  render(<App />);
  expect(await screen.findByTestId("empty-state")).toBeInTheDocument();
});

it("/landing is an alias: lands on Landing content", async () => {
  vi.mocked(api.me).mockRejectedValue(new ApiError("Unauthorized."));
  window.history.pushState({}, "", "/landing");
  render(<App />);
  expect(await screen.findByTestId("landing-hero")).toBeInTheDocument();
  // Navigate/ alias uses the router's internal navigate (bypasses useNavigate mock).
  expect(window.location.pathname).toBe("/");
});

it("logged-in user at / still sees the Landing (trang chủ)", async () => {
  // Root is ALWAYS Landing, even logged in (user report: "đăng nhập rồi không
  // nhảy về trang chủ được nữa").
  vi.mocked(api.me).mockResolvedValue({
    id: 1,
    email: "user@x.io",
    role: "user",
  } as User);
  render(<App />);
  // Settle authed first: nav-avatar only renders once me resolves.
  // (Old code redirects in the same commit → landing-hero gone → this fails.)
  await userEvent.click(await screen.findByTestId("nav-avatar"));
  expect(screen.getByTestId("landing-hero")).toBeInTheDocument();
  expect(screen.queryByTestId("empty-state")).not.toBeInTheDocument();
  expect(window.location.pathname).toBe("/");
});

it("logged-out auth-zone (RIGHT) has btn-login + nav-link-signup; NO left nav-link-login", async () => {
  // Realistic logged-out: /api/auth/me → 401 (data stays undefined).
  vi.mocked(api.me).mockRejectedValue(new ApiError("Unauthorized."));
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  render(<App />);
  const zone = within(await screen.findByTestId("auth-zone"));
  expect(await screen.findByTestId("btn-login")).toHaveTextContent("Sign in");
  expect(zone.getByTestId("nav-link-signup")).toHaveTextContent("Sign up");
  // Removed from left per binding contract — assertion moved here, not deleted.
  expect(screen.queryByTestId("nav-link-login")).not.toBeInTheDocument();
  expect(screen.queryByTestId("btn-logout")).not.toBeInTheDocument();
});

it("header renders quota-remaining when quota resolves; hidden when null", async () => {
  vi.mocked(api.me).mockResolvedValue({
    id: 1,
    email: "user@x.io",
    role: "user",
  } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(api.getMyQuota).mockResolvedValue({
    daily_limit: 25,
    daily_used: 10,
    weekly_limit: 150,
    weekly_used: 40,
    daily_remaining: 15,
    weekly_remaining: 110,
  });
  render(<App />);
  // Quota đầy đủ nằm trong avatar menu; nav bar chỉ còn chip gọn.
  await userEvent.click(await screen.findByTestId("nav-avatar"));
  const badge = await screen.findByTestId("quota-remaining");
  expect(badge).toHaveTextContent("15/25 pages left today");
  expect(badge).toHaveTextContent("110/150 this week");
});

it("admin sees BOTH nav-link-jobs and nav-link-admin (first-run upload path)", async () => {
  vi.mocked(api.me).mockResolvedValue({
    id: 3,
    email: "admin@x.io",
    role: "admin",
  } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  render(<App />);
  expect(await screen.findByTestId("nav-link-jobs")).toBeInTheDocument();
  expect(await screen.findByTestId("nav-link-admin")).toBeInTheDocument();
});

it("logged-in user sees nav-link-jobs, NOT nav-link-admin", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user" } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  render(<App />);
  expect(await screen.findByTestId("nav-link-jobs")).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByTestId("nav-link-admin")).not.toBeInTheDocument());
});

it("logged-in user sees btn-logout in dropdown; click calls api.logout and navigates to /signin", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, email: "user@x.io", role: "user" } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(api.logout).mockResolvedValue({});
  render(<App />);
  await userEvent.click(await screen.findByTestId("nav-avatar"));
  expect(screen.getByTestId("btn-logout")).toBeInTheDocument();
  await userEvent.click(screen.getByTestId("btn-logout"));
  await waitFor(() => expect(api.logout).toHaveBeenCalled());
  expect(mockNavigate).toHaveBeenCalledWith("/signin");
});

it("btn-profile inside dropdown links to /profile placeholder route", async () => {
  vi.mocked(api.me).mockResolvedValue({
    id: 1,
    email: "user@x.io",
    role: "user",
  } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  render(<App />);
  await userEvent.click(await screen.findByTestId("nav-avatar"));
  await userEvent.click(screen.getByTestId("btn-profile"));
  expect(await screen.findByRole("heading", { name: "Profile" })).toBeInTheDocument();
});

it("user dropdown: nav-avatar opens nav-user-menu containing email + role", async () => {
  vi.mocked(api.me).mockResolvedValue({
    id: 7,
    email: "menu@x.io",
    role: "user",
  } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  render(<App />);
  const avatar = await screen.findByTestId("nav-avatar");
  await userEvent.click(avatar);
  const menu = screen.getByTestId("nav-user-menu");
  expect(menu).toHaveTextContent("menu@x.io");
  expect(menu).toHaveTextContent("user");
});

it("outside click closes the user dropdown menu (mousedown outside wrapper)", async () => {
  vi.mocked(api.me).mockResolvedValue({
    id: 7,
    email: "menu@x.io",
    role: "user",
  } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  render(<App />);
  await userEvent.click(await screen.findByTestId("nav-avatar"));
  expect(screen.getByTestId("nav-user-menu")).toBeInTheDocument();
  fireEvent.mouseDown(document);
  expect(screen.queryByTestId("nav-user-menu")).not.toBeInTheDocument();
});

it("clicking nav-avatar again closes the dropdown (toggle)", async () => {
  vi.mocked(api.me).mockResolvedValue({
    id: 7,
    email: "menu@x.io",
    role: "user",
  } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  render(<App />);
  const avatar = await screen.findByTestId("nav-avatar");
  await userEvent.click(avatar);
  expect(screen.getByTestId("nav-user-menu")).toBeInTheDocument();
  await userEvent.click(avatar);
  expect(screen.queryByTestId("nav-user-menu")).not.toBeInTheDocument();
});

// P2: me → undefined (logout) must reset menuOpen; re-login must not auto-open menu.
it("AuthZone: logout (me=undefined) resets menu open state for re-login", async () => {
  const meUser = { id: 1, email: "user@x.io", role: "user" } as User;
  const wrap = (me: User | undefined) => (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <AuthZone me={me} onLogout={() => {}} />
      </MemoryRouter>
    </QueryClientProvider>
  );
  const { rerender } = render(wrap(meUser));
  await userEvent.click(screen.getByTestId("nav-avatar"));
  expect(screen.getByTestId("nav-user-menu")).toBeInTheDocument();
  // Logout: me → undefined.
  rerender(wrap(undefined));
  // Re-login: menu must NOT auto-open (stale menuOpen reset by effect).
  rerender(wrap(meUser));
  expect(screen.getByTestId("nav-avatar")).toBeInTheDocument();
  expect(screen.queryByTestId("nav-user-menu")).not.toBeInTheDocument();
});

it("/word and /edit redirect to / (standalone /edit page removed; R51 user instruction)", async () => {
  vi.mocked(api.me).mockRejectedValue(new ApiError("Unauthorized."));
  for (const route of ["/word", "/edit"]) {
    window.history.pushState({}, "", route);
    const view = render(<App />);
    expect(await screen.findByTestId("landing-hero")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/");
    view.unmount();
  }
});

// D6: trang /features gộp vào Landing → bookmark cũ redirect /#roadmap.
it("/features redirects to / with the roadmap anchor", async () => {
  vi.mocked(api.me).mockRejectedValue(new ApiError("Unauthorized."));
  window.history.pushState({}, "", "/features");
  render(<App />);
  expect(await screen.findByTestId("landing-roadmap")).toBeInTheDocument();
  expect(window.location.pathname).toBe("/");
  expect(window.location.hash).toBe("#roadmap");
});

it("hamburger toggle: aria-expanded/controls/label, opens mobile menu, closes on link click", async () => {
  render(<App />);
  const toggle = screen.getByTestId("nav-menu-toggle");
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(toggle).toHaveAttribute("aria-controls", "mobile-menu");
  expect(toggle).toHaveAttribute("aria-label", "Menu");
  expect(screen.queryByTestId("mobile-menu")).not.toBeInTheDocument();
  await userEvent.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  const menu = screen.getByTestId("mobile-menu");
  expect(within(menu).getByTestId("nav-link-jobs")).toBeInTheDocument();
  await userEvent.click(within(menu).getByTestId("nav-link-jobs"));
  await waitFor(() => expect(screen.queryByTestId("mobile-menu")).not.toBeInTheDocument());
});

// Task 2 + root fix: "Công việc" active ONLY at /jobs — never on the / landing.
it("nav-link-jobs has aria-current=page ONLY at /jobs, not at /", async () => {
  vi.mocked(api.me).mockRejectedValue(new ApiError("Unauthorized."));
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  render(<App />);
  expect(await screen.findByTestId("nav-link-jobs")).not.toHaveAttribute("aria-current");
});

it("nav-link-jobs carries aria-current=page at /jobs", async () => {
  vi.mocked(api.me).mockRejectedValue(new ApiError("Unauthorized."));
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  window.history.pushState({}, "", "/jobs");
  render(<App />);
  expect(await screen.findByTestId("nav-link-jobs")).toHaveAttribute("aria-current", "page");
});

/**
 * Lane 1 — spec 2026-11-03 AC1–AC4: layout mode addressable in the URL.
 * Route-level assertions belong here (this file owns the real App route table);
 * component-level mode behaviour stays in pages/JobDetail.test.tsx and
 * components/UnifiedEditor.test.tsx.
 */
const LAYOUT_RESULT: ResultBody = {
  model_version: "test",
  gpu_seconds: 0,
  warnings: [],
  markdown: "# Doc",
  pages: [],
  edited_markdown: null,
};

const LAYOUT_JOB: Job = {
  id: 5,
  status: "done",
  file_type: "pdf",
  page_count: 1,
  error: null,
  result: LAYOUT_RESULT,
  created_at: "2026-01-02T03:04:05Z",
  started_at: null,
  finished_at: null,
  output_format: "md",
  layout_cache: { md: true, docx: true },
  layout_style: null,
  text_version: 1,
};

/** Job done + export/preview chain; `output_format` = mode mặc định của /jobs/:id/layout. */
function mockLayoutJob(output_format: "md" | "docx" = "md") {
  vi.mocked(api.me).mockRejectedValue(new ApiError("Unauthorized."));
  vi.mocked(api.getJob).mockResolvedValue({ ...LAYOUT_JOB, output_format });
  vi.mocked(api.exportJob).mockResolvedValue({ url: "" });
  vi.mocked(api.downloadExport).mockResolvedValue(new Blob(["# Doc"]));
  vi.mocked(api.getDocxHtml).mockResolvedValue(null);
  vi.mocked(api.getLayoutPreviewHtml).mockResolvedValue(null);
  vi.mocked(mammoth.convertToHtml).mockResolvedValue({
    value: "<p>Doc</p>",
    messages: [],
  } as never);
}

function renderAt(path: string) {
  window.history.pushState({}, "", path);
  return render(<App />);
}

it("AC1: /jobs/5/layout/word renders word mode without clicking a mode switch", async () => {
  mockLayoutJob("md"); // output_format=md → URL phải thắng
  renderAt("/jobs/5/layout/word");
  // Read-only preview nhận mode từ URL ngay ở mount.
  expect(await screen.findByTestId("preview-word")).toBeInTheDocument();
  expect(screen.queryByTestId("preview-md")).toBeNull();
  // Editor = MÀN RIÊNG: btn-edit-doc điều hướng, mode đi theo URL.
  await userEvent.click(screen.getByTestId("btn-edit-doc"));
  await waitFor(() => expect(window.location.pathname).toBe("/jobs/5/edit/word"));
  expect(mockNavigate).toHaveBeenCalledWith("/jobs/5/edit/word");
  await screen.findByTestId("preview-docx-frame");
  expect(screen.queryByTestId("md-editor")).toBeNull();
});

it("AC1: /jobs/5/layout/md renders md mode without clicking a mode switch", async () => {
  mockLayoutJob("docx"); // output_format=docx → URL phải thắng
  renderAt("/jobs/5/layout/md");
  expect(await screen.findByTestId("preview-md")).toBeInTheDocument();
  expect(screen.queryByTestId("preview-word")).toBeNull();
  await userEvent.click(screen.getByTestId("btn-edit-doc"));
  await waitFor(() => expect(window.location.pathname).toBe("/jobs/5/edit/md"));
  expect(await screen.findByTestId("md-editor")).toBeInTheDocument();
  expect(screen.queryByTestId("preview-docx-frame")).toBeNull();
});

it.each([["docx", "word"], ["md", "md"]] as const)(
  "AC3+AC4: /jobs/5/layout resolves output_format=%s → %s and does not redirect",
  async (output_format, expected) => {
    mockLayoutJob(output_format);
    renderAt("/jobs/5/layout");
    // Preview vẫn ở /layout (không redirect), mode resolve từ output_format.
    expect(await screen.findByTestId("btn-edit-doc")).toBeInTheDocument();
    // AC4: edit nằm ở route riêng, mode đi theo URL của nó.
    await userEvent.click(screen.getByTestId("btn-edit-doc"));
    await waitFor(() =>
      expect(window.location.pathname).toBe(`/jobs/5/edit/${expected}`),
    );
    if (expected === "word") {
      await screen.findByTestId("preview-docx-frame");
      expect(screen.queryByTestId("md-editor")).toBeNull();
    } else {
      await screen.findByTestId("md-editor");
      expect(screen.queryByTestId("preview-docx-frame")).toBeNull();
    }
  },
);

it("AC2: switch-mode-word trong màn edit điều hướng /jobs/5/edit/word", async () => {
  mockLayoutJob("md");
  renderAt("/jobs/5/edit/md");
  await screen.findByTestId("md-editor");
  await userEvent.click(screen.getByTestId("switch-mode-word"));
  await waitFor(() => expect(window.location.pathname).toBe("/jobs/5/edit/word"));
  expect(mockNavigate).toHaveBeenCalledWith("/jobs/5/edit/word");
  // Mode đi theo URL: word container, md unmount.
  expect(await screen.findByTestId("preview-docx-frame")).toBeInTheDocument();
  expect(screen.queryByTestId("md-editor")).toBeNull();
});

it("AC2: back/forward giữ mode — URL là nguồn sự thật", async () => {
  mockLayoutJob("md");
  renderAt("/jobs/5/edit/md");
  await screen.findByTestId("md-editor");
  await userEvent.click(screen.getByTestId("switch-mode-word"));
  await waitFor(() => expect(window.location.pathname).toBe("/jobs/5/edit/word"));
  window.history.back();
  await waitFor(() => expect(window.location.pathname).toBe("/jobs/5/edit/md"));
  expect(await screen.findByTestId("md-editor")).toBeInTheDocument();
});

it("AC8 (/legal): route công khai — render nội dung, KHÔNG bị VerifyGate chặn", async () => {
  // Chưa verify + chưa đăng nhập vẫn đọc được ToS (link từ checkbox signup).
  vi.mocked(api.me).mockResolvedValue({
    id: 1,
    email: "u@x.io",
    role: "user",
    is_verified: false,
  } as User);
  window.history.pushState({}, "", "/legal");
  render(<App />);
  expect(
    await screen.findByRole("heading", { level: 1, name: "Terms of Service" }),
  ).toBeInTheDocument();
  expect(screen.getByTestId("legal-data")).toBeInTheDocument();
  expect(screen.queryByTestId("verify-modal")).not.toBeInTheDocument();
});
