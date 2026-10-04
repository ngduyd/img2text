import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "./api/client";
import type { User } from "./api/types";
import App from "./App";

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
});

it("renders app shell with brand and nav links", () => {
  render(<App />);
  expect(screen.getByTestId("nav-brand")).toHaveTextContent("img2text");
  expect(screen.getByTestId("nav-link-jobs")).toBeInTheDocument();
  expect(screen.getByTestId("nav-link-admin")).toBeInTheDocument();
});

it("nav-link-login always in DOM", () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.listJobs).mockResolvedValue({ items: [], total: 0 });
  render(<App />);
  expect(screen.getByTestId("nav-link-login")).toBeInTheDocument();
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
