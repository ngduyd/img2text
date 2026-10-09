import { expect, it } from "vitest";
import type { JobStatus } from "../../src/api/types";
import { STATUS_TEXT, STATUS_TONE } from "../../src/lib/status";

// Plan job-phases: exactly 5 statuses, exact Vietnamese labels (Global Constraints).
const ALL_STATUSES = ["done", "extracting", "failed", "queued", "rendering"] as JobStatus[];

it("STATUS_TEXT pins the 5 exact status labels", () => {
  expect(STATUS_TEXT).toEqual({
    queued: "Đang lập lịch",
    extracting: "Đang trích xuất văn bản",
    rendering: "Đang dựng layout",
    done: "Hoàn tất",
    failed: "Xử lý thất bại",
  });
});

it("STATUS_TONE covers all 5 statuses; extracting and rendering use distinct hues", () => {
  expect(Object.keys(STATUS_TONE).sort()).toEqual([...ALL_STATUSES].sort());
  expect(STATUS_TONE.extracting).not.toBe(STATUS_TONE.rendering);
});
