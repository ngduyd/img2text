import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { api, ApiError } from "../api/client";
import type { User } from "../api/types";
import Profile from "./Profile";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
      updateProfile: vi.fn(),
    },
  };
});

/** Page tests: MemoryRouter + QueryClientProvider (App wraps both in prod). */
function renderWithRouter(ui: ReactElement, { route = "/profile" } = {}) {
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

const USER: User = { id: 7, email: "u@x.io", role: "user", ocr_enabled: true };

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.me).mockResolvedValue(USER);
});

it("renders info card: email, role badge, ocr badge, id, join note", async () => {
  renderWithRouter(<Profile />);
  expect(await screen.findByTestId("profile-email")).toHaveTextContent("u@x.io");
  expect(screen.getByTestId("profile-role")).toHaveTextContent("User");
  expect(screen.getByTestId("badge-ocr-profile")).toHaveTextContent("OCR đã cấp");
  expect(screen.getByTestId("profile-id")).toHaveTextContent("7");
  expect(screen.getByText("Ngày tham gia: cập nhật sau")).toBeInTheDocument();
});

it("password submit calls updateProfile with exact args", async () => {
  vi.mocked(api.updateProfile).mockResolvedValue(USER);
  renderWithRouter(<Profile />);
  const user = userEvent.setup();
  await user.type(await screen.findByTestId("input-current-password"), "Old123!");
  await user.type(screen.getByTestId("input-new-password"), "New123!");
  await user.type(screen.getByTestId("input-new-password2"), "New123!");
  await user.click(screen.getByTestId("btn-save-password"));
  expect(api.updateProfile).toHaveBeenCalledWith({
    current_password: "Old123!",
    new_password: "New123!",
  });
});

it("password success message after update", async () => {
  vi.mocked(api.updateProfile).mockResolvedValue(USER);
  renderWithRouter(<Profile />);
  const user = userEvent.setup();
  await user.type(await screen.findByTestId("input-current-password"), "Old123!");
  await user.type(screen.getByTestId("input-new-password"), "New123!");
  await user.type(screen.getByTestId("input-new-password2"), "New123!");
  await user.click(screen.getByTestId("btn-save-password"));
  expect(await screen.findByTestId("password-success")).toHaveTextContent(
    "Đổi mật khẩu thành công. Phiên đăng nhập khác đã bị đăng xuất.",
  );
});

it("email submit calls updateProfile with exact args and shows success", async () => {
  vi.mocked(api.updateProfile).mockResolvedValue({ ...USER, email: "new@x.io" });
  renderWithRouter(<Profile />);
  const user = userEvent.setup();
  await user.type(await screen.findByTestId("input-current-password-2"), "Old123!");
  await user.type(screen.getByTestId("input-new-email"), "new@x.io");
  await user.click(screen.getByTestId("btn-save-email"));
  expect(api.updateProfile).toHaveBeenCalledWith({
    current_password: "Old123!",
    email: "new@x.io",
  });
  expect(await screen.findByTestId("email-success")).toHaveTextContent("Đổi email thành công.");
  // me cache updated from PATCH response
  expect(await screen.findByTestId("profile-email")).toHaveTextContent("new@x.io");
});

it("409 duplicate email surfaces ApiError detail in email-error", async () => {
  vi.mocked(api.updateProfile).mockRejectedValue(new ApiError("Email đã tồn tại."));
  renderWithRouter(<Profile />);
  const user = userEvent.setup();
  await user.type(await screen.findByTestId("input-current-password-2"), "Old123!");
  await user.type(screen.getByTestId("input-new-email"), "dup@x.io");
  await user.click(screen.getByTestId("btn-save-email"));
  expect(await screen.findByTestId("email-error")).toHaveTextContent("Email đã tồn tại.");
});

it("password mismatch is client-side: error text, NO api call", async () => {
  renderWithRouter(<Profile />);
  const user = userEvent.setup();
  await user.type(await screen.findByTestId("input-current-password"), "Old123!");
  await user.type(screen.getByTestId("input-new-password"), "Aaa123!");
  await user.type(screen.getByTestId("input-new-password2"), "Bbb123!");
  await user.click(screen.getByTestId("btn-save-password"));
  expect(await screen.findByTestId("password-error")).toHaveTextContent(
    "Mật khẩu xác nhận không khớp.",
  );
  expect(api.updateProfile).not.toHaveBeenCalled();
});
