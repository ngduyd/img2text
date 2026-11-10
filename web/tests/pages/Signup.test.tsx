import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../src/api/client";
import type { User } from "../../src/api/types";
import Signup from "../../src/pages/Signup";

const mockNavigate = vi.fn();

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => mockNavigate };
});

vi.mock("../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      login: vi.fn(),
      register: vi.fn(),
    },
  };
});

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function renderSignup() {
  const client = new QueryClient();
  return render(<Signup />, {
    wrapper: ({ children }) => (
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/signup"]}>{children}</MemoryRouter>
      </QueryClientProvider>
    ),
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

it("gate ToS: btn-register disabled tới khi tick checkbox", async () => {
  renderSignup();
  const btn = screen.getByTestId("btn-register");
  expect(btn).toBeDisabled();
  await userEvent.click(screen.getByTestId("input-tos"));
  expect(btn).toBeEnabled();
  // untick → khoá lại
  await userEvent.click(screen.getByTestId("input-tos"));
  expect(btn).toBeDisabled();
});

it("checkbox có link tới /legal", () => {
  renderSignup();
  expect(screen.getByRole("link", { name: /terms of service/i })).toHaveAttribute(
    "href",
    "/legal",
  );
});

it("submit gửi accept_tos: true", async () => {
  vi.mocked(api.register).mockResolvedValue({ status: "ok" });
  vi.mocked(api.login).mockResolvedValue({
    id: 1,
    email: "t@x.io",
    role: "user",
    is_verified: false,
  } as User);
  renderSignup();
  await userEvent.type(screen.getByTestId("input-email"), "t@x.io");
  await userEvent.type(screen.getByTestId("input-password"), "secret123");
  await userEvent.click(screen.getByTestId("input-tos"));
  await userEvent.click(screen.getByTestId("btn-register"));
  await waitFor(() =>
    expect(api.register).toHaveBeenCalledWith("t@x.io", "secret123", true),
  );
});
