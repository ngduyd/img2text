import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { ApiError, api } from "./api/client";
import type { User } from "./api/types";
import App, { queryClient } from "./App";

vi.mock("./api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api/client")>();
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

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return {
    ...actual,
    useNavigate: () => mockNavigate,
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
  expect(screen.getByTestId("nav-link-jobs")).toBeInTheDocument();
  // R51: admin link is role-gated (binding nav contract) — asserted in admin test.
  expect(screen.queryByTestId("nav-link-admin")).not.toBeInTheDocument();
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
  expect(avatar).toHaveAttribute("title", "user");
  expect(await screen.findByTestId("btn-profile")).toHaveTextContent("Hồ sơ");
  expect(await screen.findByTestId("btn-logout")).toHaveTextContent("Đăng xuất");
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

it("logged-in user sees btn-logout; click calls api.logout and navigates to /login", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  vi.mocked(api.logout).mockResolvedValue({});
  render(<App />);
  expect(await screen.findByTestId("btn-logout")).toBeInTheDocument();
  await userEvent.click(screen.getByTestId("btn-logout"));
  await waitFor(() => expect(api.logout).toHaveBeenCalled());
  expect(mockNavigate).toHaveBeenCalledWith("/login");
});

it("btn-profile links to /profile placeholder route", async () => {
  vi.mocked(api.me).mockResolvedValue({
    id: 1,
    email: "user@x.io",
    role: "user",
    ocr_enabled: true,
  } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  render(<App />);
  await userEvent.click(await screen.findByTestId("btn-profile"));
  expect(await screen.findByRole("heading", { name: "Hồ sơ" })).toBeInTheDocument();
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
