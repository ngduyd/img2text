import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { toast } from "sonner";
import { api } from "../../../src/api/client";
import type { User } from "../../../src/api/types";
import AdminUsers from "../../../src/pages/admin/AdminUsers";

vi.mock("../../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../src/api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      adminListUsers: vi.fn(),
      adminPatchQuota: vi.fn(),
    },
  };
});

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AdminUsers />
    </QueryClientProvider>,
  );
}

const quotaUser = {
  id: 2,
  email: "a@x.io",
  role: "user",
  ocr_enabled: true,
  daily_limit: 25,
  daily_used: 3,
  daily_remaining: 22,
  weekly_limit: 150,
  weekly_used: 3,
  weekly_remaining: 147,
} as User;

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.adminListUsers).mockResolvedValue({ items: [quotaUser], total: 1 });
});

it("shows quota columns (đã dùng/còn) per user", async () => {
  renderPage();
  const cell = await screen.findByTestId("quota-2");
  expect(cell).toHaveTextContent("3/25");
  expect(cell).toHaveTextContent("còn 22");
  expect(cell).toHaveTextContent("3/150");
});

it("inline edit 2 limits → PATCH quota + toast R59 + invalidate", async () => {
  vi.mocked(api.adminPatchQuota).mockResolvedValue(undefined);
  renderPage();
  const user = userEvent.setup();
  await user.clear(await screen.findByTestId("daily-limit-2"));
  await user.type(screen.getByTestId("daily-limit-2"), "5");
  await user.clear(screen.getByTestId("weekly-limit-2"));
  await user.type(screen.getByTestId("weekly-limit-2"), "50");
  await user.click(screen.getByTestId("save-quota-2"));
  await waitFor(() =>
    expect(api.adminPatchQuota).toHaveBeenCalledWith(2, {
      daily_page_limit: 5,
      weekly_page_limit: 50,
    }),
  );
  // R59: success toast
  expect(toast.success).toHaveBeenCalledWith("Đã lưu.");
  // invalidate → list refetch (quota hiển thị lại từ server)
  await waitFor(() => expect(vi.mocked(api.adminListUsers).mock.calls.length).toBeGreaterThan(1));
});
