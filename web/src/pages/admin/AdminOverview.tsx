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
    </div>
  );
}
