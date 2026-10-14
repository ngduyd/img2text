import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { ApiError, api } from "../../src/api/client";
import VerifyModal from "../../src/components/VerifyModal";

vi.mock("../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/api/client")>();
  return {
    ...actual,
    api: { ...actual.api, verifyCode: vi.fn(), verifyResend: vi.fn() },
  };
});

function renderModal(props: Partial<ComponentProps<typeof VerifyModal>> = {}) {
  return render(
    <MemoryRouter>
      <VerifyModal {...props} />
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.useRealTimers();
  vi.clearAllMocks();
});

it("renders R51 testid verify-modal, fullscreen dialog không dismiss", () => {
  renderModal();
  const dialog = screen.getByTestId("verify-modal");
  expect(dialog).toHaveAttribute("role", "dialog");
  expect(dialog).toHaveAttribute("aria-modal", "true");
  // Overlay che nội dung thay vì ẩn: fixed toàn màn hình.
  expect(dialog.className).toContain("fixed");
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
    "Verify your email",
  );
  expect(screen.queryByTestId("btn-close")).not.toBeInTheDocument();
});

it("input mã 6 số: inputmode numeric + maxLength 6, chỉ nhận số", async () => {
  renderModal();
  const input = screen.getByTestId("input-code");
  expect(input).toHaveAttribute("inputmode", "numeric");
  expect(input).toHaveAttribute("maxlength", "6");
  await userEvent.type(input, "ab12-3456");
  expect(input).toHaveValue("123456");
});

it("submit mã đúng → verifyCode + onVerified (refetch profile unlock)", async () => {
  vi.mocked(api.verifyCode).mockResolvedValue({});
  const onVerified = vi.fn();
  renderModal({ onVerified });
  await userEvent.type(screen.getByTestId("input-code"), "123456");
  await userEvent.click(screen.getByTestId("btn-verify"));
  await waitFor(() => expect(api.verifyCode).toHaveBeenCalledWith("123456"));
  await waitFor(() => expect(onVerified).toHaveBeenCalledTimes(1));
});

it("submit mã sai → hiện lỗi map từ server detail 422", async () => {
  vi.mocked(api.verifyCode).mockRejectedValue(new ApiError("invalid or expired code"));
  renderModal();
  await userEvent.type(screen.getByTestId("input-code"), "000000");
  await userEvent.click(screen.getByTestId("btn-verify"));
  expect(await screen.findByTestId("error-detail")).toHaveTextContent(
    "Invalid or expired code.",
  );
  // Hết hạn = cùng detail → cùng 1 message i18n.
  expect(screen.getByTestId("error-detail")).not.toHaveTextContent("invalid or expired");
});

it("chưa đủ 6 số → btn-verify disabled", () => {
  renderModal();
  expect(screen.getByTestId("btn-verify")).toBeDisabled();
});

it("TTL countdown 5:00 local + resend cooldown chạy sau resend thật", async () => {
  vi.useFakeTimers();
  renderModal();
  expect(screen.getByTestId("verify-ttl")).toHaveTextContent("5:00");

  // P2 review fix: cooldown khởi động 0 — gating-triggered open không
  // bị chặn 30s oan (code cũ có thể đã hết hạn, cần resend ngay).
  const resend = screen.getByTestId("btn-resend");
  expect(resend).toBeEnabled();
  expect(resend).toHaveTextContent("Resend code");

  await act(async () => vi.advanceTimersByTime(1000));
  expect(screen.getByTestId("verify-ttl")).toHaveTextContent("4:59");

  vi.mocked(api.verifyResend).mockResolvedValue({});
  await act(async () => {
    fireEvent.click(screen.getByTestId("btn-resend"));
  });
  expect(api.verifyResend).toHaveBeenCalledTimes(1);
  // Code mới → TTL reset 5:00 + cooldown 30s chạy SAU resend.
  expect(screen.getByTestId("verify-ttl")).toHaveTextContent("5:00");
  expect(screen.getByTestId("btn-resend")).toBeDisabled();
  expect(screen.getByTestId("btn-resend")).toHaveTextContent("Resend code in 30s");
  await act(async () => vi.advanceTimersByTime(30000));
  expect(screen.getByTestId("btn-resend")).toBeEnabled();
});

it("resend 429 {code:email_limit} → lỗi i18n, không reset cooldown", async () => {
  vi.useFakeTimers();
  vi.mocked(api.verifyResend).mockRejectedValue(new ApiError("HTTP 429", "email_limit"));
  renderModal();
  await act(async () => vi.advanceTimersByTime(30000));
  await act(async () => {
    fireEvent.click(screen.getByTestId("btn-resend"));
  });
  expect(screen.getByTestId("error-detail")).toHaveTextContent(
    "Too many emails requested. Please try again later.",
  );
  expect(screen.getByTestId("verify-ttl")).toHaveTextContent("4:30");
});
