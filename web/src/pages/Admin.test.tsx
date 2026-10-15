/** Lane AD: Workers + GPU/Kaggle Quota → tab System (trước: card luôn-đồ-nhìn mọi tab). */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import Admin from "./Admin";

const h = vi.hoisted(() => ({
  me: vi.fn(),
  getWorkers: vi.fn(),
  getKaggleQuota: vi.fn(),
  getAdminSettings: vi.fn(),
}));

vi.mock("../api/client", () => ({
  api: new Proxy({}, {
    get: (_t, k: string) =>
      k === "me" ? h.me :
      k === "getWorkers" ? h.getWorkers :
      k === "getKaggleQuota" ? h.getKaggleQuota :
      k === "getAdminSettings" ? h.getAdminSettings :
      vi.fn().mockResolvedValue({}),
  }),
}));

// Overview thuộc lane khác — fake; test này chỉ đo rail + mount System.
vi.mock("./admin/AdminOverview", () => ({ default: () => null }));

beforeEach(() => {
  vi.clearAllMocks();
  h.me.mockResolvedValue({ role: "admin" });
  h.getWorkers.mockResolvedValue({ queue_depth: 0, items: [] });
  h.getKaggleQuota.mockResolvedValue({
    gpu: { used_s: 100, total_s: 21600, remaining_s: 21500, refresh: null },
    tpu: { used_s: 0, total_s: 72000, remaining_s: 72000, refresh: null },
  });
  h.getAdminSettings.mockResolvedValue({
    kaggle_mode: { value: "gpu", source: "env" },
  });
});

function renderAdmin() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Admin />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

test("rail đủ 8 tab — Workers/Quota không còn card mọi tab", async () => {
  renderAdmin();
  await screen.findByTestId("admin-rail");
  expect(screen.getAllByTestId(/^tab-/)).toHaveLength(8);
  await waitFor(() =>
    expect(screen.queryByTestId("admin-workers")).not.toBeInTheDocument(),
  );
  expect(screen.queryByTestId("kaggle-quota")).not.toBeInTheDocument();
});

test("System tab mount Workers + GPU Quota cùng card-settings", async () => {
  renderAdmin();
  fireEvent.click(await screen.findByTestId("tab-settings"));
  const workers = await screen.findByTestId("admin-workers");
  const quota = await screen.findByTestId("kaggle-quota");
  const settings = screen.getByTestId("card-settings");
  // cùng wrapper System section
  expect(workers.parentElement).toContainElement(settings);
  expect(workers.parentElement).toContainElement(quota);
});
