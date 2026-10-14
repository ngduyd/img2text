/** Review R1 P2: invalid quota → field error (error prop), controlled input. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import AdminUsers from "./AdminUsers";

const listUsers = vi.fn();
const patchQuota = vi.fn();

vi.mock("../../api/client", () => ({
  api: {
    adminListUsers: (...a: unknown[]) => listUsers(...a),
    adminPatchQuota: (...a: unknown[]) => patchQuota(...a),
    adminPatchUser: vi.fn(),
  },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const USER = {
  id: 2,
  email: "u@test.io",
  role: "user",
  ocr_enabled: false,
  created_at: "2026-01-01T00:00:00Z",
  daily_limit: 25,
  daily_used: 0,
  daily_remaining: 25,
  weekly_limit: 150,
  weekly_used: 0,
  weekly_remaining: 150,
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AdminUsers />
    </QueryClientProvider>,
  );
}

beforeEach(() => vi.clearAllMocks());

test("invalid quota input → field error, patch không gọi", async () => {
  listUsers.mockResolvedValue({ items: [USER], total: 1 });
  renderPage();
  const daily = await screen.findByTestId("daily-limit-2");
  fireEvent.change(daily, { target: { value: "100001" } });
  fireEvent.click(screen.getByTestId("save-quota-2"));
  await waitFor(() =>
    expect(screen.getAllByRole("alert")[0]).toHaveTextContent("between 0 and 10000"),
  );
  expect(daily).toHaveValue(100001); // controlled: giá trị gõ giữ nguyên
  expect(patchQuota).not.toHaveBeenCalled();
});
