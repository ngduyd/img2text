import { useEffect, useRef } from "react";
import { toast } from "sonner";
import type { JobStatus } from "../api/types";
import { translate } from "../i18n";
import { PENDING_STATUSES } from "../lib/status";

/** Job subset theo dõi transition pending → terminal (spec #2). */
export interface WatchedJob {
  id: number;
  status: JobStatus;
  error?: string | null;
  /** Tên file nếu server có; vắng → dùng #id. */
  filename?: string | null;
}

/** Đã xin permission Notification lần đầu chưa (1 lần cho cả phiên — spec #2). */
let notificationPermissionAsked = false;

/** Browser Notification: best-effort — unsupported/uncaught → nuốt, không crash. */
function notifyDone(job: WatchedJob) {
  try {
    if (typeof Notification === "undefined") return;
    if (Notification.permission === "default" && !notificationPermissionAsked) {
      notificationPermissionAsked = true;
      void Notification.requestPermission().catch(() => {});
    }
    if (Notification.permission === "granted") {
      new Notification("img2text", {
        body: translate("toast.jobDone", { name: job.filename ?? `#${job.id}` }),
      });
    }
  } catch {
    // best-effort — sandbox/browser có thể ném
  }
}

/**
 * Spec #2: theo dõi status transitions của job(s) đang poll —
 * pending → done → toast.success; pending → failed → toast.error.
 * Mount đã terminal → không toast (không re-fire khi poll giữ nguyên status).
 */
export function useJobDoneToasts(jobs: WatchedJob[] | undefined) {
  const prev = useRef(new Map<number, JobStatus>());
  // JSON identity: query object mới mỗi poll → so sánh thô là đủ (không cần deep).
  const stamp = JSON.stringify(jobs);
  useEffect(() => {
    const seen = prev.current;
    for (const j of jobs ?? []) {
      const before = seen.get(j.id);
      seen.set(j.id, j.status);
      // Lần đầu thấy job (mount đã done) → bỏ qua.
      if (before === undefined || before === j.status) continue;
      if (!PENDING_STATUSES.includes(before)) continue;
      if (j.status === "done") {
        toast.success(translate("toast.jobDone", { name: j.filename ?? `#${j.id}` }));
        notifyDone(j);
      } else if (j.status === "failed") {
        toast.error(
          j.error
            ? translate("toast.jobFailedWith", { id: j.id, error: j.error })
            : translate("toast.jobFailed", { id: j.id }),
        );
      }
    }
    // eslint/oxlint: stamp là snapshot của jobs.
  }, [stamp, jobs]);
}
