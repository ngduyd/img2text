/** Lane C2 P1-2: submit code stale trả already_verified (detail hoặc code) →
 *  coi như verified, gọi onVerified (refetch me + đóng modal), không kẹt form. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, test, vi } from "vitest";

const verifyCode = vi.fn();

vi.mock("../api/client", () => {
  class ApiError extends Error {
    detail: string;
    code?: string;
    constructor(detail: string, code?: string) {
      super(detail);
      this.detail = detail;
      this.code = code;
    }
  }
  return {
    ApiError,
    api: { verifyCode: (...a: unknown[]) => verifyCode(...a), verifyResend: vi.fn() },
  };
});

import { ApiError } from "../api/client";
import VerifyModal from "./VerifyModal";

function submitCode() {
  fireEvent.change(screen.getByTestId("input-code"), { target: { value: "123456" } });
  fireEvent.click(screen.getByTestId("btn-verify"));
}

beforeEach(() => vi.clearAllMocks());

test("submit already_verified theo code → onVerified, không hiện lỗi", async () => {
  verifyCode.mockRejectedValue(new ApiError("already verified", "already_verified"));
  const onVerified = vi.fn();
  render(
    <MemoryRouter>
      <VerifyModal email="a@b.c" onVerified={onVerified} />
    </MemoryRouter>,
  );
  submitCode();
  await waitFor(() => expect(onVerified).toHaveBeenCalledTimes(1));
  expect(screen.queryByTestId("error-detail")).toBeNull();
});

test("cooldown khởi đầu 0 — resend bật ngay khi mount, chỉ chặn sau khi resend thật", () => {
  render(
    <MemoryRouter>
      <VerifyModal />
    </MemoryRouter>,
  );
  expect(screen.getByTestId("btn-resend")).toBeEnabled();
});

test("autofocus input code khi modal mount", () => {
  render(
    <MemoryRouter>
      <VerifyModal />
    </MemoryRouter>,
  );
  expect(screen.getByTestId("input-code")).toHaveFocus();
});

test("submit already_verified theo detail (không có code) → onVerified", async () => {
  verifyCode.mockRejectedValue(new ApiError("already_verified"));
  const onVerified = vi.fn();
  render(
    <MemoryRouter>
      <VerifyModal onVerified={onVerified} />
    </MemoryRouter>,
  );
  submitCode();
  await waitFor(() => expect(onVerified).toHaveBeenCalledTimes(1));
  expect(screen.queryByTestId("error-detail")).toBeNull();
});
