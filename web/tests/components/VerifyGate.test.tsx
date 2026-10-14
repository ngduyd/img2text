import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { api, request } from "../../src/api/client";
import type { User } from "../../src/api/types";
import VerifyGate from "../../src/components/VerifyGate";

vi.mock("../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/api/client")>();
  return {
    ...actual,
    // Spread giữ onEmailUnverified/request THẬT (shared listener set với gate).
    api: { ...actual.api, me: vi.fn(), logout: vi.fn(), verifyCode: vi.fn() },
  };
});

const VERIFIED = {
  id: 1,
  email: "u@x.io",
  role: "user",
  ocr_enabled: true,
  is_verified: true,
} as User;
const UNVERIFIED = { ...VERIFIED, is_verified: false } as User;

function renderGate(route = "/jobs") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>
        <VerifyGate />
        <div data-testid="page-content" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

it("me is_verified=false → verify-modal overlay, KHÔNG ẩn nội dung", async () => {
  vi.mocked(api.me).mockResolvedValue(UNVERIFIED);
  renderGate();
  expect(await screen.findByTestId("verify-modal")).toBeInTheDocument();
  // Nội dung vẫn render đằng sau overlay (modal che, không ẩn).
  expect(screen.getByTestId("page-content")).toBeInTheDocument();
});

it("me is_verified=true → không modal", async () => {
  vi.mocked(api.me).mockResolvedValue(VERIFIED);
  renderGate();
  await waitFor(() => expect(vi.mocked(api.me)).toHaveBeenCalledTimes(1));
  expect(screen.queryByTestId("verify-modal")).not.toBeInTheDocument();
});

it("route exempt (login/register/features) → không modal dù unverified", async () => {
  vi.mocked(api.me).mockResolvedValue(UNVERIFIED);
  renderGate("/signin");
  await waitFor(() => expect(vi.mocked(api.me)).toHaveBeenCalledTimes(1));
  expect(screen.queryByTestId("verify-modal")).not.toBeInTheDocument();
});

it("403 email_unverified từ bất kỳ API call nào → mở modal", async () => {
  vi.mocked(api.me).mockResolvedValue(VERIFIED);
  renderGate("/jobs");
  await waitFor(() => expect(vi.mocked(api.me)).toHaveBeenCalledTimes(1));
  expect(screen.queryByTestId("verify-modal")).not.toBeInTheDocument();

  // API khác trả 403 flat {code:"email_unverified"} (middleware S5).
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify({ code: "email_unverified" }), { status: 403 }),
    ),
  );
  await request("/api/jobs").catch(() => {});
  expect(await screen.findByTestId("verify-modal")).toBeInTheDocument();
  expect(screen.getByTestId("page-content")).toBeInTheDocument();
});

it("submit mã đúng → refetch [\"me\"] verified → đóng modal (unlock)", async () => {
  vi.mocked(api.me).mockResolvedValue(UNVERIFIED);
  vi.mocked(api.verifyCode).mockResolvedValue({});
  renderGate();
  await screen.findByTestId("verify-modal");

  // Sau verify server trả is_verified=true → invalidate ["me"] refetch → đóng.
  vi.mocked(api.me).mockResolvedValue(VERIFIED);
  await userEvent.type(screen.getByTestId("input-code"), "123456");
  await userEvent.click(screen.getByTestId("btn-verify"));
  await waitFor(() =>
    expect(screen.queryByTestId("verify-modal")).not.toBeInTheDocument(),
  );
  expect(api.verifyCode).toHaveBeenCalledWith("123456");
});
