/** Lane B2 (wave-5 S6): trang /feedback — textarea + char count + submit. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, test, vi } from "vitest";

const submitFeedback = vi.fn();
const toastSuccess = vi.fn();

vi.mock("../api/client", () => ({
  api: { submitFeedback: (...a: unknown[]) => submitFeedback(...a) },
}));
vi.mock("sonner", () => ({
  toast: { success: (...a: unknown[]) => toastSuccess(...a), error: vi.fn() },
}));

import Feedback from "./Feedback";

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Feedback />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => vi.clearAllMocks());

test("char count cập nhật khi gõ", async () => {
  renderPage();
  const ta = await screen.findByTestId("feedback-content");
  fireEvent.change(ta, { target: { value: "hello" } });
  expect(screen.getByTestId("feedback-count").textContent).toBe("5/2000");
});

test("submit → api.submitFeedback + toast success", async () => {
  window.history.pushState({}, "", "/feedback");
  submitFeedback.mockResolvedValue({ id: 1 });
  renderPage();
  const ta = await screen.findByTestId("feedback-content");
  fireEvent.change(ta, { target: { value: "trang này hay" } });
  fireEvent.submit(screen.getByTestId("feedback-content").closest("form")!);
  await waitFor(() =>
    expect(submitFeedback).toHaveBeenCalledWith("trang này hay", "/feedback"),
  );
  expect(toastSuccess).toHaveBeenCalled();
});

test("rỗng → submit disabled", async () => {
  renderPage();
  const btn = await screen.findByTestId("feedback-submit");
  expect(btn).toBeDisabled();
});

test("quá 2000 ký tự → submit disabled", async () => {
  renderPage();
  const ta = await screen.findByTestId("feedback-content");
  fireEvent.change(ta, { target: { value: "x".repeat(2001) } });
  expect(screen.getByTestId("feedback-submit")).toBeDisabled();
  expect(screen.getByTestId("feedback-count").textContent).toBe("2001/2000");
});
