import { expect, it } from "vitest";
import type { JobStatus } from "../../src/api/types";
import { STATUS_KEY, STATUS_TONE } from "../../src/lib/status";

// Job phases: exactly 6 statuses (spec cancel lane), i18n keys (dicts hold text).
const ALL_STATUSES = ["done", "extracting", "failed", "queued", "rendering", "cancelled"] as JobStatus[];

it("STATUS_KEY pins the 6 exact status keys", () => {
  expect(STATUS_KEY).toEqual({
    queued: "status.queued",
    extracting: "status.extracting",
    rendering: "status.rendering",
    done: "status.done",
    failed: "status.failed",
    cancelled: "status.cancelled",
  });
});

it("STATUS_TONE covers all 6 statuses; extracting and rendering use distinct hues", () => {
  expect(Object.keys(STATUS_TONE).sort()).toEqual([...ALL_STATUSES].sort());
  expect(STATUS_TONE.extracting).not.toBe(STATUS_TONE.rendering);
});
