import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { AdminStatsDay } from "../../api/types";
import { Stat } from "../../components/ui/Stat";
import { useT } from "../../i18n";
import { last7Days } from "./dateRange";

export type AdminTabId = "overview" | "users" | "api" | "logs" | "stats" | "storage" | "settings" | "feedbacks";

const CARDS = [
  { id: "users", labelKey: "admin.overview.newUsers", sum: (d: AdminStatsDay) => d.users_registered },
  { id: "done", labelKey: "admin.overview.jobsDone", sum: (d: AdminStatsDay) => d.jobs_done },
  { id: "failed", labelKey: "admin.overview.jobsFailed", sum: (d: AdminStatsDay) => d.jobs_failed },
  { id: "gpu", labelKey: "admin.overview.gpuTotal", sum: (d: AdminStatsDay) => d.gpu_seconds },
  { id: "cost", labelKey: "admin.overview.cost", sum: (d: AdminStatsDay) => d.estimated_cost_usd },
  { id: "emailsSent", labelKey: "admin.overview.emailsSent", sum: (d: AdminStatsDay) => d.emails_sent },
  { id: "emailsFailed", labelKey: "admin.overview.emailsFailed", sum: (d: AdminStatsDay) => d.emails_failed },
] as const;

/**
 * Stat cards: sums across adminStats(7d) days[].
 * D10: 7 số liệu trên MỘT hàng; bỏ 4 nút "đi tới tab" — trùng với rail.
 */
/**
 * Cột job xong/lỗi theo ngày (data `days[]` đã có sẵn trong adminStats).
 * Không thêm thư viện chart: 7 cột, 1 series xếp chồng, đọc bằng aria-label.
 */
function ActivityChart({ days }: { days: AdminStatsDay[] }) {
  const { t } = useT();
  const max = Math.max(1, ...days.map((d) => d.jobs_done + d.jobs_failed));
  const totalDone = days.reduce((s, d) => s + d.jobs_done, 0);
  const totalFailed = days.reduce((s, d) => s + d.jobs_failed, 0);
  return (
    <section
      data-testid="admin-activity"
      className="mt-4 rounded-card border border-border bg-surface p-4 shadow-card"
    >
      <h2 className="text-sm font-semibold">
        {t("admin.overview.activity", { done: totalDone, failed: totalFailed })}
      </h2>
      <div className="mt-3 flex h-28 items-end gap-2" role="img" aria-label={t("admin.overview.activityAria", { done: totalDone, failed: totalFailed })}>
        {days.map((d) => {
          const done = (d.jobs_done / max) * 100;
          const failed = (d.jobs_failed / max) * 100;
          return (
            <div key={d.date} className="flex min-w-0 flex-1 flex-col items-center gap-1 self-stretch">
              <div className="flex w-full flex-1 flex-col justify-end" title={`${d.date}: ${d.jobs_done} xong, ${d.jobs_failed} lỗi`}>
                <div className="w-full rounded-t-sm bg-error/60" style={{ height: `${failed}%` }} />
                <div className="w-full bg-accent/70" style={{ height: `${done}%` }} />
              </div>
              <span className="text-[10px] tabular-nums text-muted">{d.date.slice(5)}</span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

export default function AdminOverview() {
  const { t } = useT();
  const range = last7Days();
  const { data } = useQuery({
    queryKey: ["admin-stats", range.from, range.to],
    queryFn: () => api.adminStats(range.from, range.to),
  });
  const days = data?.days ?? [];

  return (
    <div>
      {(data?.emails_stuck ?? 0) > 0 && (
        <p role="status" className="mb-4 text-sm text-error">
          {t("admin.overview.emailsStuck", { n: data!.emails_stuck })}
        </p>
      )}
      <p className="mb-2 text-sm text-muted">{t("admin.overview.rangeHint")}</p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-7">
        {CARDS.map((c) => (
          /* p-3 + min-h: 7 card/hàng ở 1200px, label 2 dòng vẫn thẳng hàng. */
          <div
            key={c.id}
            data-testid={`stat-${c.id}`}
            className="flex min-h-20 flex-col justify-between rounded-card border border-border bg-surface p-3 shadow-card"
          >
            <Stat label={t(c.labelKey)} value={String(days.reduce((s, d) => s + c.sum(d), 0))} />
          </div>
        ))}
      </div>
      <ActivityChart days={days} />
    </div>
  );
}
