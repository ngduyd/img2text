import type { Job } from "../api/types";
import type { BadgeTone } from "../components/ui/Badge";

/** Spec §status: Vietnamese job status texts (single spelling: shell, panels, badges). */
export const STATUS_TEXT: Record<Job["status"], string> = {
  queued: "Đang chờ worker Colab",
  running: "Đang xử lý",
  failed: "Xử lý thất bại",
  done: "Hoàn tất",
};

export const STATUS_TONE: Record<Job["status"], BadgeTone> = {
  queued: "neutral",
  running: "info",
  failed: "error",
  done: "success",
};
