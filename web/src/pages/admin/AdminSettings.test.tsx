/** Lane CFG: AdminSettings — 5 section (LLM/Kaggle/Scheduler/Limits/SMTP),
 * nguồn badge env|db, reset về env (DELETE), nút Test model (test-model flow),
 * save per-section (payload chỉ gồm field của section đó). */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import AdminSettings from "./AdminSettings";

const getAdminSettings = vi.fn();
const putAdminSettings = vi.fn();
const deleteAdminSetting = vi.fn();
const testLlmModel = vi.fn();

vi.mock("../../api/client", () => ({
  ApiError: class ApiError extends Error {
    detail = "";
  },
  api: {
    getAdminSettings: (...a: unknown[]) => getAdminSettings(...a),
    putAdminSettings: (...a: unknown[]) => putAdminSettings(...a),
    deleteAdminSetting: (...a: unknown[]) => deleteAdminSetting(...a),
    testLlmModel: (...a: unknown[]) => testLlmModel(...a),
  },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const ENV = "env";
const DB = "db";
const settings = () => ({
  llm_base_url: { value: "http://localhost:20128/v1", source: ENV },
  llm_model: { value: "layout-1", source: ENV },
  ir_llm_model: { value: "ir-1", source: ENV },
  proofread_llm_model: { value: "proof-1", source: ENV },
  llm_api_key: { value: null, source: ENV },
  llm_timeout: { value: 180, source: ENV },
  kaggle_min_queue: { value: 1, source: ENV },
  kaggle_min_gap_seconds: { value: 60, source: ENV },
  kaggle_mode: { value: "batch", source: ENV },
  scheduler_interval_seconds: { value: 60, source: ENV },
  purge_interval_seconds: { value: 3600, source: ENV },
  purge_retention_days: { value: 7, source: ENV },
  max_pages: { value: 100, source: ENV },
  daily_page_limit: { value: 25, source: ENV },
  weekly_page_limit: { value: 150, source: ENV },
  upload_byte_limit: { value: 211812352, source: ENV },
  smtp_host: { value: "localhost", source: ENV },
  smtp_port: { value: 25, source: ENV },
  smtp_user: { value: "", source: ENV },
  smtp_pass: { value: null, source: ENV },
  smtp_from: { value: "noreply@example.com", source: ENV },
});

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AdminSettings />
    </QueryClientProvider>,
  );
}

beforeEach(() => vi.clearAllMocks());

test("renders 5 sections with heading, fields, source badge, readonly mode", async () => {
  getAdminSettings.mockResolvedValue(settings());
  renderPage();
  await screen.findByTestId("form-settings");
  for (const heading of ["LLM", "Kaggle GPU", "Scheduler", "Limits", "SMTP"]) {
    expect(screen.getByRole("heading", { name: heading, level: 3 })).toBeTruthy();
  }
  // field + nguồn badge
  expect(await screen.findByTestId("input-max-pages")).toHaveValue(100);
  expect(screen.getByTestId("source-max-pages")).toHaveTextContent("env");
  expect(screen.getByTestId("input-smtp-host")).toHaveValue("localhost");
  expect(screen.getByTestId("input-ir-llm-model")).toHaveValue("ir-1");
  // upload_byte_limit hiển thị MB (211812352 B = 202 MB)
  expect(screen.getByTestId("input-upload-byte-limit")).toHaveValue(202);
  // write-only: ô pass không prefill mask
  expect(screen.getByTestId("input-smtp-pass")).toHaveValue("");
  // kaggle_mode readonly
  expect(screen.getByTestId("kaggle-mode-value")).toHaveTextContent("batch");
  // nút Test cạnh mỗi ô model + reset mỗi ô
  for (const slug of ["llm-model", "ir-llm-model", "proofread-llm-model"]) {
    expect(screen.getByTestId(`test-${slug}`)).toBeTruthy();
  }
  expect(screen.getByTestId("reset-max-pages")).toBeTruthy();
});

test("per-section save gửi chỉ field của section đó", async () => {
  getAdminSettings.mockResolvedValue(settings());
  putAdminSettings.mockResolvedValue(settings());
  renderPage();
  await screen.findByTestId("form-settings");
  fireEvent.change(screen.getByTestId("input-smtp-host"), {
    target: { value: "smtp.new.example" },
  });
  fireEvent.click(screen.getByTestId("btn-save-smtp"));
  await waitFor(() => expect(putAdminSettings).toHaveBeenCalledTimes(1));
  expect(putAdminSettings).toHaveBeenCalledWith(
    expect.objectContaining({ smtp_host: "smtp.new.example", smtp_port: 25 }),
  );
  const payload = putAdminSettings.mock.calls[0][0];
  expect(payload).not.toHaveProperty("scheduler_interval_seconds");
  expect(payload).not.toHaveProperty("max_pages");
});

test("reset về env: DELETE row → badge env", async () => {
  getAdminSettings.mockResolvedValue(settings());
  deleteAdminSetting.mockResolvedValue(settings());
  renderPage();
  await screen.findByTestId("form-settings");
  fireEvent.change(screen.getByTestId("input-max-pages"), {
    target: { value: "42" },
  });
  // save trước → nguồn db (refetch sau invalidate trả về db)
  getAdminSettings.mockResolvedValue({
    ...settings(),
    max_pages: { value: 42, source: DB },
  });
  fireEvent.click(screen.getByTestId("btn-save-limits"));
  await waitFor(() =>
    expect(screen.getByTestId("source-max-pages")).toHaveTextContent("db"),
  );
  // reset → DELETE + badge về env
  fireEvent.click(screen.getByTestId("reset-max-pages"));
  await waitFor(() =>
    expect(deleteAdminSetting).toHaveBeenCalledWith("max_pages"),
  );
  await waitFor(() =>
    expect(screen.getByTestId("source-max-pages")).toHaveTextContent("env"),
  );
  expect(screen.getByTestId("input-max-pages")).toHaveValue(100);
});

test("Test model: ok → badge Sống + latency; fail → badge Chết", async () => {
  getAdminSettings.mockResolvedValue(settings());
  testLlmModel.mockResolvedValue({
    ok: true,
    latency_ms: 123,
    model: "ir-1",
    error: null,
  });
  renderPage();
  await screen.findByTestId("form-settings");
  fireEvent.click(screen.getByTestId("test-ir-llm-model"));
  await waitFor(() => expect(testLlmModel).toHaveBeenCalledTimes(1));
  // P2f: gửi kèm base_url đang nhập trong form (test đúng URL admin sửa)
  expect(testLlmModel).toHaveBeenCalledWith({
    model: "ir-1",
    base_url: "http://localhost:20128/v1",
  });
  await waitFor(() =>
    expect(screen.getByTestId("test-result-ir-llm-model")).toHaveTextContent(
      "Alive · 123 ms",
    ),
  );
  // fail → Chết + lỗi
  testLlmModel.mockResolvedValue({
    ok: false,
    latency_ms: 5,
    model: "ir-1",
    error: "HTTP 500: boom",
  });
  fireEvent.click(screen.getByTestId("test-ir-llm-model"));
  await waitFor(() =>
    expect(screen.getByTestId("test-result-ir-llm-model")).toHaveTextContent(
      "Dead",
    ),
  );
  expect(
    screen.getByTestId("test-result-ir-llm-model"),
  ).toHaveTextContent("HTTP 500");
});

test("floor client-side: max_pages 0 → ô lỗi, không PUT", async () => {
  getAdminSettings.mockResolvedValue(settings());
  renderPage();
  await screen.findByTestId("form-settings");
  fireEvent.change(screen.getByTestId("input-max-pages"), {
    target: { value: "0" },
  });
  fireEvent.click(screen.getByTestId("btn-save-limits"));
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(putAdminSettings).not.toHaveBeenCalled();
});
