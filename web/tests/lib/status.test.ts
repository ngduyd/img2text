import { expect, it } from "vitest";
import type { JobStatus } from "../../src/api/types";
import { STATUS_TEXT, STATUS_TONE } from "../../src/lib/status";

// Job phases: exactly 6 statuses (spec cancel lane), exact Vietnamese labels.
const ALL_STATUSES = ["done", "extracting", "failed", "queued", "rendering", "cancelled"] as JobStatus[];

it("STATUS_TEXT pins the 6 exact status labels", () => {
  expect(STATUS_TEXT).toEqual({
    queued: "Đang lập lịch",
    extracting: "Đang trích xuất văn bản",
    rendering: "Đang dựng layout",
    done: "Hoàn tất",
    failed: "Xử lý thất bại",
    cancelled: "Đã hủy",
  });
});

it("STATUS_TONE covers all 6 statuses; extracting and rendering use distinct hues", () => {
  expect(Object.keys(STATUS_TONE).sort()).toEqual([...ALL_STATUSES].sort());
  expect(STATUS_TONE.extracting).not.toBe(STATUS_TONE.rendering);
});
