/** Lane B2 (wave-5 S6): admin feedbacks list — content/email/page/date + pagination. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

const adminListFeedbacks = vi.fn();

vi.mock("../../api/client", () => ({
  api: { adminListFeedbacks: (...a: unknown[]) => adminListFeedbacks(...a) },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import AdminFeedbacks from "./AdminFeedbacks";

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AdminFeedbacks />
    </QueryClientProvider>,
  );
}

const PAGE1 = {
  items: [
    {
      id: 2,
      content: "mới nhất",
      page_path: "/jobs",
      user_id: 1,
      email: "a@t.io",
      created_at: "2026-10-15T10:00:00+00:00",
    },
  ],
  total: 21,
};

beforeEach(() => vi.clearAllMocks());

test("render row: content, email, page, date + total", async () => {
  adminListFeedbacks.mockResolvedValue(PAGE1);
  renderCard();
  expect((await screen.findByTestId("fb-row-2")).textContent).toContain("mới nhất");
  expect(screen.getByTestId("fb-row-2").textContent).toContain("a@t.io");
  expect(screen.getByTestId("fb-row-2").textContent).toContain("/jobs");
  expect(screen.getByTestId("fb-total").textContent).toContain("21");
  expect(adminListFeedbacks).toHaveBeenCalledWith(1, 20);
});

test("next → page 2", async () => {
  adminListFeedbacks.mockResolvedValue(PAGE1);
  renderCard();
  await screen.findByTestId("fb-row-2");
  fireEvent.click(screen.getByTestId("fb-next"));
  await waitFor(() => expect(adminListFeedbacks).toHaveBeenCalledWith(2, 20));
});

test("empty list → empty state", async () => {
  adminListFeedbacks.mockResolvedValue({ items: [], total: 0 });
  renderCard();
  expect(await screen.findByTestId("fb-empty")).toBeInTheDocument();
});

test("prev disabled ở page 1", async () => {
  adminListFeedbacks.mockResolvedValue(PAGE1);
  renderCard();
  await screen.findByTestId("fb-row-2");
  expect(screen.getByTestId("fb-prev")).toBeDisabled();
});
