import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { ApiError, api } from "../src/api/client";
import type { User } from "../src/api/types";
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
    },
  };
});

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
    // working. Trailing-undefined args dropped so toHaveBeenCalledWith("/login")
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

it("/ renders Landing publicly (hero H1 + CTA to /login)", async () => {
  vi.mocked(api.me).mockRejectedValue(new ApiError("Unauthorized."));
  render(<App />);
  expect(await screen.findByTestId("landing-hero")).toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
    "Biến ảnh và PDF thành văn bản sửa được",
  );
  expect(screen.getByTestId("landing-cta")).toHaveAttribute("href", "/login");
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
    ocr_enabled: true,
  } as User);
  render(<App />);
  // Settle authed first: badge-ocr only renders once me resolves.
  // (Old code redirects in the same commit → landing-hero gone → this fails.)
  expect(await screen.findByTestId("badge-ocr")).toHaveTextContent("OCR đã cấp");
  expect(screen.getByTestId("landing-hero")).toBeInTheDocument();
  expect(screen.queryByTestId("empty-state")).not.toBeInTheDocument();
  expect(window.location.pathname).toBe("/");
});

it("logged-out auth-zone (RIGHT) has btn-login + btn-register; NO left nav-link-login", async () => {
  // Realistic logged-out: /api/auth/me → 401 (data stays undefined).
  vi.mocked(api.me).mockRejectedValue(new ApiError("Unauthorized."));
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  render(<App />);
  const zone = within(await screen.findByTestId("auth-zone"));
  expect(await screen.findByTestId("btn-login")).toHaveTextContent("Đăng nhập");
  expect(zone.getByTestId("btn-register")).toHaveTextContent("Đăng ký");
  // Removed from left per binding contract — assertion moved here, not deleted.
  expect(screen.queryByTestId("nav-link-login")).not.toBeInTheDocument();
  expect(screen.queryByTestId("btn-logout")).not.toBeInTheDocument();
});

it("logged-in user sees badge-ocr success + avatar + profile + logout in auth-zone", async () => {
  vi.mocked(api.me).mockResolvedValue({
    id: 1,
    email: "user@x.io",
    role: "user",
    ocr_enabled: true,
  } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  render(<App />);
  const zone = within(await screen.findByTestId("auth-zone"));
  expect(await screen.findByTestId("badge-ocr")).toHaveTextContent("OCR đã cấp");
  const avatar = await screen.findByTestId("nav-avatar");
  expect(avatar).toHaveTextContent("US");
  expect(avatar).toHaveAttribute("title", "user@x.io");
  expect(avatar).toHaveAttribute("aria-expanded", "false");
  expect(avatar).toHaveAttribute("aria-haspopup", "menu");
  // Profile/logout live inside the dropdown — hidden until nav-avatar opens it.
  expect(zone.queryByTestId("btn-profile")).not.toBeInTheDocument();
  expect(zone.queryByTestId("btn-logout")).not.toBeInTheDocument();
  await userEvent.click(avatar);
  expect(avatar).toHaveAttribute("aria-expanded", "true");
  const menu = screen.getByTestId("nav-user-menu");
  expect(menu).toHaveTextContent("user@x.io");
  expect(menu).toHaveTextContent("user");
  expect(within(menu).getByTestId("btn-profile")).toHaveTextContent("Hồ sơ");
  expect(within(menu).getByTestId("btn-logout")).toHaveTextContent("Đăng xuất");
  expect(zone.queryByTestId("btn-login")).not.toBeInTheDocument();
});

it("user without OCR sees badge-ocr warning in auth-zone", async () => {
  vi.mocked(api.me).mockResolvedValue({
    id: 2,
    email: "b@x.io",
    role: "user",
    ocr_enabled: false,
  } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  render(<App />);
  expect(await screen.findByTestId("badge-ocr")).toHaveTextContent("Chờ admin cấp quyền");
});

it("admin sees BOTH nav-link-jobs and nav-link-admin (first-run upload path)", async () => {
  vi.mocked(api.me).mockResolvedValue({
    id: 3,
    email: "admin@x.io",
    role: "admin",
    ocr_enabled: true,
  } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  render(<App />);
  expect(await screen.findByTestId("nav-link-jobs")).toBeInTheDocument();
  expect(await screen.findByTestId("nav-link-admin")).toBeInTheDocument();
});

it("logged-in user sees nav-link-jobs, NOT nav-link-admin", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  render(<App />);
  expect(await screen.findByTestId("nav-link-jobs")).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByTestId("nav-link-admin")).not.toBeInTheDocument());
});

it("logged-in user sees btn-logout in dropdown; click calls api.logout and navigates to /login", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, email: "user@x.io", role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(api.logout).mockResolvedValue({});
  render(<App />);
  await userEvent.click(await screen.findByTestId("nav-avatar"));
  expect(screen.getByTestId("btn-logout")).toBeInTheDocument();
  await userEvent.click(screen.getByTestId("btn-logout"));
  await waitFor(() => expect(api.logout).toHaveBeenCalled());
  expect(mockNavigate).toHaveBeenCalledWith("/login");
});

it("btn-profile inside dropdown links to /profile placeholder route", async () => {
  vi.mocked(api.me).mockResolvedValue({
    id: 1,
    email: "user@x.io",
    role: "user",
    ocr_enabled: true,
  } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  render(<App />);
  await userEvent.click(await screen.findByTestId("nav-avatar"));
  await userEvent.click(screen.getByTestId("btn-profile"));
  expect(await screen.findByRole("heading", { name: "Hồ sơ" })).toBeInTheDocument();
});

it("user dropdown: nav-avatar opens nav-user-menu containing email + role", async () => {
  vi.mocked(api.me).mockResolvedValue({
    id: 7,
    email: "menu@x.io",
    role: "user",
    ocr_enabled: true,
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
    ocr_enabled: true,
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
    ocr_enabled: true,
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
  const meUser = { id: 1, email: "user@x.io", role: "user", ocr_enabled: true } as User;
  const { rerender } = render(
    <MemoryRouter>
      <AuthZone me={meUser} onLogout={() => {}} />
    </MemoryRouter>,
  );
  await userEvent.click(screen.getByTestId("nav-avatar"));
  expect(screen.getByTestId("nav-user-menu")).toBeInTheDocument();
  // Logout: me → undefined.
  rerender(
    <MemoryRouter>
      <AuthZone me={undefined} onLogout={() => {}} />
    </MemoryRouter>,
  );
  // Re-login: menu must NOT auto-open (stale menuOpen reset by effect).
  rerender(
    <MemoryRouter>
      <AuthZone me={meUser} onLogout={() => {}} />
    </MemoryRouter>,
  );
  expect(screen.getByTestId("nav-avatar")).toBeInTheDocument();
  expect(screen.queryByTestId("nav-user-menu")).not.toBeInTheDocument();
});

it("/word alias redirects to /edit (WordTool page moved; R51 user instruction)", async () => {
  vi.mocked(api.me).mockRejectedValue(new ApiError("Unauthorized."));
  window.history.pushState({}, "", "/word");
  render(<App />);
  expect(await screen.findByTestId("edit-page")).toBeInTheDocument();
  expect(window.location.pathname).toBe("/edit");
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
