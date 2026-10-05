import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { ApiError, api } from "../api/client";
import type { User } from "../api/types";
import { toast } from "sonner";
import Forgot from "./Forgot";
import Login from "./Login";
import Register from "./Register";
import Reset from "./Reset";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      login: vi.fn(),
      register: vi.fn(),
      forgotEmail: vi.fn(),
      resetPassword: vi.fn(),
    },
  };
});

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

/** App.tsx BrowserRouter is for prod; page tests use MemoryRouter per page. */
function renderWithRouter(ui: ReactElement, { route = "/" } = {}) {
  return render(ui, {
    wrapper: ({ children }) => (
      <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
    ),
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

it("login button exists and submits credentials", async () => {
  vi.mocked(api.login).mockResolvedValue({} as User);
  renderWithRouter(<Login />);
  await userEvent.type(screen.getByTestId("input-email"), "u@x.io");
  await userEvent.type(screen.getByTestId("input-password"), "secret123");
  await userEvent.click(screen.getByTestId("btn-login"));
  expect(screen.getByTestId("btn-login")).toBeInTheDocument();
  expect(api.login).toHaveBeenCalledWith("u@x.io", "secret123");
});

it("login shows server detail error", async () => {
  vi.mocked(api.login).mockRejectedValue(new ApiError("Sai mật khẩu."));
  renderWithRouter(<Login />);
  await userEvent.click(screen.getByTestId("btn-login"));
  expect(await screen.findByText("Sai mật khẩu.")).toBeInTheDocument();
  // R59: failing login also toasts mapped detail.
  expect(toast.error).toHaveBeenCalledWith("Sai mật khẩu.");
});

it("register button exists and submits", async () => {
  vi.mocked(api.register).mockResolvedValue({} as User);
  renderWithRouter(<Register />);
  await userEvent.click(screen.getByTestId("btn-register"));
  expect(api.register).toHaveBeenCalled();
});

it("forgot shows constant success message", async () => {
  vi.mocked(api.forgotEmail).mockResolvedValue({});
  renderWithRouter(<Forgot />);
  await userEvent.click(screen.getByTestId("btn-forgot"));
  expect(await screen.findByText("Kiểm tra email của bạn.")).toBeInTheDocument();
});

it("reset submits token from query", async () => {
  vi.mocked(api.resetPassword).mockResolvedValue({});
  renderWithRouter(<Reset />, { route: "/reset?token=abc123" });
  await userEvent.click(screen.getByTestId("btn-reset"));
  expect(api.resetPassword).toHaveBeenCalledWith("abc123", expect.any(String));
});
