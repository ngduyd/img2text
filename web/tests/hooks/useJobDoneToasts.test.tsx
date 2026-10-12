import { renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { toast } from "sonner";
import { useJobDoneToasts } from "../../src/hooks/useJobDoneToasts";
import type { JobStatus } from "../../src/api/types";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

type Watched = { id: number; status: JobStatus; error?: string | null; filename?: string | null };

function hook(initial: Watched[]) {
  return renderHook(({ jobs }) => useJobDoneToasts(jobs), { initialProps: { jobs: initial } });
}

beforeEach(() => {
  vi.clearAllMocks();
});

it("pending → done fires success toast once", () => {
  const { rerender } = hook([{ id: 1, status: "queued" }]);
  rerender({ jobs: [{ id: 1, status: "done" }] });
  expect(toast.success).toHaveBeenCalledTimes(1);
  expect(toast.success).toHaveBeenCalledWith("Job đã xong: #1");
  // Poll tiếp (done → done) KHÔNG toast lại.
  rerender({ jobs: [{ id: 1, status: "done" }] });
  expect(toast.success).toHaveBeenCalledTimes(1);
});

it("pending → done with filename → toast dùng tên file thật", () => {
  const { rerender } = hook([{ id: 9, status: "queued", filename: "sach-viet.pdf" }]);
  rerender({ jobs: [{ id: 9, status: "done", filename: "sach-viet.pdf" }] });
  expect(toast.success).toHaveBeenCalledWith("Job đã xong: sach-viet.pdf");
});

it("pending → failed fires error toast", () => {
  const { rerender } = hook([{ id: 2, status: "extracting" }]);
  rerender({ jobs: [{ id: 2, status: "failed", error: "boom" }] });
  expect(toast.error).toHaveBeenCalledWith("Job #2 thất bại: boom");
  expect(toast.success).not.toHaveBeenCalled();
});

it("mounted already done → no toast on first render or later polls", () => {
  const { rerender } = hook([{ id: 3, status: "done" }]);
  expect(toast.success).not.toHaveBeenCalled();
  rerender({ jobs: [{ id: 3, status: "done" }] });
  expect(toast.success).not.toHaveBeenCalled();
});

it("requests Notification permission once on first done (best-effort)", () => {
  const requestPermission = vi.fn().mockResolvedValue("denied");
  const Notif = { permission: "default", requestPermission } as unknown as typeof Notification;
  vi.stubGlobal("Notification", Notif);
  hook([{ id: 10, status: "queued" }]).rerender({ jobs: [{ id: 10, status: "done" }] });
  hook([{ id: 11, status: "queued" }]).rerender({ jobs: [{ id: 11, status: "done" }] });
  expect(requestPermission).toHaveBeenCalledTimes(1);
});

it("Notification unsupported → không throw", () => {
  vi.stubGlobal("Notification", undefined);
  expect(() =>
    hook([{ id: 12, status: "queued" }]).rerender({ jobs: [{ id: 12, status: "done" }] }),
  ).not.toThrow();
});
