import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { toast } from "sonner";
import { api, ApiError } from "../../../src/api/client";
import type { AdminSettings, User } from "../../../src/api/types";
import Admin from "../../../src/pages/Admin";
import AdminSettingsPage from "../../../src/pages/admin/AdminSettings";

vi.mock("../../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../src/api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
      adminStats: vi.fn(),
      getAdminSettings: vi.fn(),
      putAdminSettings: vi.fn(),
    },
  };
});

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => mockNavigate };
});

function renderPage(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/admin"]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

const SETTINGS: AdminSettings = {
  scheduler_interval_seconds: { value: 60, source: "env" },
  kaggle_min_queue: { value: 1, source: "db" },
  kaggle_min_gap_seconds: { value: 600, source: "env" },
  kaggle_mode: { value: "batch", source: "env" },
  llm_base_url: { value: "http://localhost:20128/v1", source: "env" },
  llm_model: { value: "oc/muse-spark-1.3-contributor-free", source: "env" },
  proofread_llm_model: { value: "oc/fledge-alpha-free", source: "env" },
  llm_api_key: { value: "", source: "env" },
};

const adminMe = { id: 1, role: "admin", ocr_enabled: true } as User;

beforeEach(() => {
  vi.clearAllMocks();
});

it("renders effective values with per-field source badges", async () => {
  vi.mocked(api.getAdminSettings).mockResolvedValue(SETTINGS);
  renderPage(<AdminSettingsPage />);
  await waitFor(() =>
    expect(screen.getByTestId("input-scheduler-interval")).toHaveValue(60),
  );
  expect(screen.getByTestId("input-kaggle-min-queue")).toHaveValue(1);
  expect(screen.getByTestId("input-kaggle-min-gap")).toHaveValue(600);
  expect(screen.getByTestId("source-scheduler-interval")).toHaveTextContent("env");
  expect(screen.getByTestId("source-kaggle-min-queue")).toHaveTextContent("db");
  // kaggle_mode: read-only row (no input)
  expect(screen.getByTestId("kaggle-mode-value")).toHaveTextContent("batch");
  expect(screen.getByText(/read-only/)).toBeInTheDocument();
});

it("save sends int values via PUT and toasts success", async () => {
  vi.mocked(api.getAdminSettings).mockResolvedValue(SETTINGS);
  vi.mocked(api.putAdminSettings).mockResolvedValue({
    ...SETTINGS,
    scheduler_interval_seconds: { value: 30, source: "db" },
    kaggle_min_queue: { value: 2, source: "db" },
    kaggle_min_gap_seconds: { value: 300, source: "db" },
  });
  renderPage(<AdminSettingsPage />);
  await waitFor(() =>
    expect(screen.getByTestId("input-scheduler-interval")).toHaveValue(60),
  );
  const user = userEvent.setup();
  await user.clear(screen.getByTestId("input-scheduler-interval"));
  await user.type(screen.getByTestId("input-scheduler-interval"), "30");
  await user.clear(screen.getByTestId("input-kaggle-min-queue"));
  await user.type(screen.getByTestId("input-kaggle-min-queue"), "2");
  await user.clear(screen.getByTestId("input-kaggle-min-gap"));
  await user.type(screen.getByTestId("input-kaggle-min-gap"), "300");
  await user.click(screen.getByTestId("btn-save-settings"));
  await waitFor(() =>
    expect(api.putAdminSettings).toHaveBeenCalledWith({
      scheduler_interval_seconds: 30,
      kaggle_min_queue: 2,
      kaggle_min_gap_seconds: 300,
      // Admin LLM settings (merged in c9cb90a) are part of the save payload.
      llm_base_url: "http://localhost:20128/v1",
      llm_model: "oc/muse-spark-1.3-contributor-free",
      proofread_llm_model: "oc/fledge-alpha-free",
    }),
  );
  expect(toast.success).toHaveBeenCalledWith("Đã lưu.");
});

it("below-floor value shows inline error, PUT skipped", async () => {
  vi.mocked(api.getAdminSettings).mockResolvedValue(SETTINGS);
  renderPage(<AdminSettingsPage />);
  await waitFor(() =>
    expect(screen.getByTestId("input-scheduler-interval")).toHaveValue(60),
  );
  const user = userEvent.setup();
  await user.clear(screen.getByTestId("input-scheduler-interval"));
  await user.type(screen.getByTestId("input-scheduler-interval"), "4");
  await user.click(screen.getByTestId("btn-save-settings"));
  expect(
    screen.getByRole("alert"),
  ).toHaveTextContent("scheduler_interval_seconds phải từ 5 giây trở lên.");
  expect(api.putAdminSettings).not.toHaveBeenCalled();
  expect(toast.success).not.toHaveBeenCalled();
});

it("server-side floor error maps inline + error toast", async () => {
  vi.mocked(api.getAdminSettings).mockResolvedValue(SETTINGS);
  vi.mocked(api.putAdminSettings).mockRejectedValue(
    new ApiError("kaggle_min_gap_seconds phải từ 60 giây trở lên."),
  );
  renderPage(<AdminSettingsPage />);
  await waitFor(() =>
    expect(screen.getByTestId("input-kaggle-min-gap")).toHaveValue(600),
  );
  const user = userEvent.setup();
  await user.click(screen.getByTestId("btn-save-settings"));
  await waitFor(() =>
    expect(api.putAdminSettings).toHaveBeenCalledWith({
      scheduler_interval_seconds: 60,
      kaggle_min_queue: 1,
      kaggle_min_gap_seconds: 600,
      // Admin LLM settings (merged in c9cb90a) are part of the save payload.
      llm_base_url: "http://localhost:20128/v1",
      llm_model: "oc/muse-spark-1.3-contributor-free",
      proofread_llm_model: "oc/fledge-alpha-free",
    }),
  );
  expect(
    await screen.findByText("kaggle_min_gap_seconds phải từ 60 giây trở lên."),
  ).toBeInTheDocument();
  expect(toast.error).toHaveBeenCalledWith(
    "kaggle_min_gap_seconds phải từ 60 giây trở lên.",
  );
});

it("renders LLM string fields with source badges", async () => {
  vi.mocked(api.getAdminSettings).mockResolvedValue(SETTINGS);
  renderPage(<AdminSettingsPage />);
  await waitFor(() =>
    expect(screen.getByTestId("input-llm-base-url")).toHaveValue(
      "http://localhost:20128/v1",
    ),
  );
  expect(screen.getByTestId("input-llm-model")).toHaveValue(
    "oc/muse-spark-1.3-contributor-free",
  );
  expect(screen.getByTestId("input-proofread-llm-model")).toHaveValue(
    "oc/fledge-alpha-free",
  );
  expect(screen.getByTestId("source-llm-base-url")).toHaveTextContent("env");
  expect(screen.getByTestId("source-llm-model")).toHaveTextContent("env");
  expect(screen.getByTestId("source-proofread-llm-model")).toHaveTextContent("env");
});

it("save sends LLM string values via PUT", async () => {
  vi.mocked(api.getAdminSettings).mockResolvedValue(SETTINGS);
  vi.mocked(api.putAdminSettings).mockResolvedValue({
    ...SETTINGS,
    llm_model: { value: "custom-model", source: "db" },
  });
  renderPage(<AdminSettingsPage />);
  await waitFor(() =>
    expect(screen.getByTestId("input-llm-model")).toHaveValue(
      "oc/muse-spark-1.3-contributor-free",
    ),
  );
  const user = userEvent.setup();
  await user.clear(screen.getByTestId("input-llm-model"));
  await user.type(screen.getByTestId("input-llm-model"), "custom-model");
  await user.click(screen.getByTestId("btn-save-settings"));
  await waitFor(() =>
    expect(api.putAdminSettings).toHaveBeenCalledWith(
      expect.objectContaining({ llm_model: "custom-model" }),
    ),
  );
  expect(toast.success).toHaveBeenCalledWith("Đã lưu.");
});

it("tab-settings renders the settings form (Admin rail)", async () => {
  vi.mocked(api.me).mockResolvedValue(adminMe);
  vi.mocked(api.adminStats).mockResolvedValue({ days: [] });
  vi.mocked(api.getAdminSettings).mockResolvedValue(SETTINGS);
  renderPage(<Admin />);
  const user = userEvent.setup();
  await user.click(await screen.findByTestId("tab-settings"));
  expect(await screen.findByTestId("form-settings")).toBeInTheDocument();
  // intro paragraph (text split by the inline <span>Setting</span>)
  expect(screen.getByTestId("form-settings").querySelector("p")).toHaveTextContent(
    "runtime override",
  );
});
