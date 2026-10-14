import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { ApiError, api } from "../../src/api/client";
import type { User } from "../../src/api/types";
import { toast } from "sonner";
import Forgot from "../../src/pages/Forgot";
import Signin from "../../src/pages/Signin";
import Signup from "../../src/pages/Signup";
import Reset from "../../src/pages/Reset";

export const mockNavigate = vi.fn();

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock("../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/api/client")>();
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

/** App.tsx BrowserRouter is for prod; page tests use MemoryRouter per page.
 *  QueryClientProvider fresh per render: Signup dùng useQueryClient (auto-login
 *  setQueryData(["me"])). */
function renderWithRouter(ui: ReactElement, { route = "/" } = {}) {
  const client = new QueryClient();
  return render(ui, {
    wrapper: ({ children }) => (
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
      </QueryClientProvider>
    ),
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

it("login button exists and submits credentials", async () => {
  vi.mocked(api.login).mockResolvedValue({} as User);
  renderWithRouter(<Signin />);
  await userEvent.type(screen.getByTestId("input-email"), "u@x.io");
  await userEvent.type(screen.getByTestId("input-password"), "secret123");
  await userEvent.click(screen.getByTestId("btn-login"));
  expect(screen.getByTestId("btn-login")).toBeInTheDocument();
  expect(api.login).toHaveBeenCalledWith("u@x.io", "secret123");
  // Post-login destination: /jobs (app list). Trang chủ "/" luôn truy cập được (nav brand).
  expect(mockNavigate).toHaveBeenCalledWith("/jobs");
});

it("login shows server detail error", async () => {
  vi.mocked(api.login).mockRejectedValue(new ApiError("Sai mật khẩu."));
  renderWithRouter(<Signin />);
  await userEvent.click(screen.getByTestId("btn-login"));
  expect(await screen.findByText("Sai mật khẩu.")).toBeInTheDocument();
  // R59: failing login also toasts mapped detail.
  expect(toast.error).toHaveBeenCalledWith("Sai mật khẩu.");
});

it("register → tự login (register không set cookie) → route theo is_verified", async () => {
  vi.mocked(api.register).mockResolvedValue({ status: "ok" });
  vi.mocked(api.login).mockResolvedValue({
    id: 1,
    email: "u@x.io",
    role: "user",
    ocr_enabled: false,
    is_verified: false,
  } as User);
  renderWithRouter(<Signup />);
  await userEvent.type(screen.getByTestId("input-email"), "u@x.io");
  await userEvent.type(screen.getByTestId("input-password"), "secret123");
  await userEvent.click(screen.getByTestId("btn-register"));
  await waitFor(() => expect(api.login).toHaveBeenCalledWith("u@x.io", "secret123"));
  // Chưa verify → trang chủ "/" (route guard VerifyGating sẽ mở modal verify).
  expect(mockNavigate).toHaveBeenCalledWith("/");
});

it("register → login: đã verify → /jobs (như login thường)", async () => {
  vi.mocked(api.register).mockResolvedValue({ status: "ok" });
  vi.mocked(api.login).mockResolvedValue({
    id: 1,
    email: "u@x.io",
    role: "user",
    ocr_enabled: false,
    is_verified: true,
  } as User);
  renderWithRouter(<Signup />);
  await userEvent.click(screen.getByTestId("btn-register"));
  await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith("/jobs"));
});

it("forgot shows constant success message", async () => {
  vi.mocked(api.forgotEmail).mockResolvedValue({});
  renderWithRouter(<Forgot />);
  await userEvent.click(screen.getByTestId("btn-forgot"));
  expect(await screen.findByText("Check your email.")).toBeInTheDocument();
});

it("reset submits token from query", async () => {
  vi.mocked(api.resetPassword).mockResolvedValue({});
  renderWithRouter(<Reset />, { route: "/reset?token=abc123" });
  await userEvent.click(screen.getByTestId("btn-reset"));
  expect(api.resetPassword).toHaveBeenCalledWith("abc123", expect.any(String));
});
