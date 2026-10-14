/** Lane K: card GPU/Kaggle Quota — render quota, format giây→giờ, refresh. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import AdminKaggleQuota from "./AdminKaggleQuota";

const getKaggleQuota = vi.fn();

vi.mock("../../api/client", () => ({
  api: {
    getKaggleQuota: (...a: unknown[]) => getKaggleQuota(...a),
  },
}));

const QUOTA = {
  gpu: {
    used_s: 5900.915,
    total_s: 21600,
    remaining_s: 15699.085,
    refresh: "2026-10-20T00:00:00Z",
  },
  tpu: {
    used_s: 7200.5,
    total_s: 72000,
    remaining_s: 64799.5,
    refresh: "2026-10-20T00:00:00Z",
  },
};

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AdminKaggleQuota />
    </QueryClientProvider>,
  );
}

beforeEach(() => vi.clearAllMocks());

test("render quota + format giây→giờ", async () => {
  getKaggleQuota.mockResolvedValue(QUOTA);
  renderCard();
  expect(
    (await screen.findByTestId("kaggle-quota-gpu")).textContent,
  ).toBe("GPU: used 1h 38m/6h · left 4h 21m");
  expect(
    (await screen.findByTestId("kaggle-quota-tpu")).textContent,
  ).toBe("TPU: used 2h/20h");
  expect(screen.getByTestId("kaggle-quota-refresh-time").textContent).toMatch(/2026/);
});

test("refresh icon → refetch", async () => {
  getKaggleQuota.mockResolvedValue(QUOTA);
  renderCard();
  await screen.findByTestId("kaggle-quota-gpu");
  fireEvent.click(screen.getByTestId("kaggle-quota-refresh"));
  await waitFor(() => expect(getKaggleQuota).toHaveBeenCalledTimes(2));
});

test("error state → chi tiết lỗi (503 kaggle missing)", async () => {
  getKaggleQuota.mockRejectedValue(new Error("kaggle package not installed"));
  renderCard();
  expect((await screen.findByTestId("kaggle-quota-error")).textContent).toMatch(
    /kaggle package not installed/,
  );
});
