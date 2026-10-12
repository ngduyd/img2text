import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { api } from "../../src/api/client";
import QuotaBadge from "../../src/components/QuotaBadge";

vi.mock("../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/api/client")>();
  return { ...actual, api: { ...actual.api, getMyQuota: vi.fn() } };
});

function renderBadge() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <QuotaBadge />
    </QueryClientProvider>,
  );
}

const QUOTA = {
  daily_limit: 25,
  daily_used: 15,
  weekly_limit: 150,
  weekly_used: 45,
  daily_remaining: 10,
  weekly_remaining: 105,
};

it("renders remaining quota text (testid quota-remaining)", async () => {
  vi.mocked(api.getMyQuota).mockResolvedValue(QUOTA);
  renderBadge();
  const el = await screen.findByTestId("quota-remaining");
  // Lane B Task 4: X/Y hôm nay + X/Y tuần này.
  expect(el).toHaveTextContent("Còn 10/25 trang hôm nay");
  expect(el).toHaveTextContent("105/150 trang tuần này");
});

it("hidden when getMyQuota returns null (401/403)", async () => {
  vi.mocked(api.getMyQuota).mockResolvedValue(null);
  renderBadge();
  await waitFor(() =>
    expect(screen.queryByTestId("quota-remaining")).not.toBeInTheDocument(),
  );
});
