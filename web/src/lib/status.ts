import type { Job } from "../api/types";
import type { BadgeTone } from "../components/ui/Badge";

/** Spec §status: Vietnamese job status texts (single spelling: shell, panels, badges). */
export const STATUS_TEXT: Record<Job["status"], string> = {
  queued: "Đang lập lịch",
  extracting: "Đang trích xuất văn bản",
  rendering: "Đang dựng layout",
  failed: "Xử lý thất bại",
  done: "Hoàn tất",
  cancelled: "Đã hủy",
};

/** Badge/chip hues from the DESIGN.md semantic palette only; extracting ≠ rendering. */
export const STATUS_TONE: Record<Job["status"], BadgeTone> = {
  queued: "neutral",
  extracting: "info",
  rendering: "warning",
  failed: "error",
  done: "success",
  cancelled: "neutral",
};

/** Plan job-phases: pending bucket = queued + extracting + rendering (Jobs stats). */
export const PENDING_STATUSES: readonly Job["status"][] = ["queued", "extracting", "rendering"];
