import type { Job } from "../api/types";
import type { BadgeTone } from "../components/ui/Badge";

/** Spec §status: single spelling per status → i18n key (dicts hold the text). */
export const STATUS_KEY: Record<Job["status"], string> = {
  queued: "status.queued",
  extracting: "status.extracting",
  rendering: "status.rendering",
  failed: "status.failed",
  done: "status.done",
  cancelled: "status.cancelled",
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
