import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { AdminStatsDay } from "../../api/types";
import Button from "../../components/ui/Button";
import Card from "../../components/ui/Card";
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

const QUICK_LINKS = [
  { tab: "users", labelKey: "admin.tab.users" },
  { tab: "api", labelKey: "admin.tab.api" },
  { tab: "logs", labelKey: "admin.tab.logs" },
  { tab: "stats", labelKey: "admin.tab.stats" },
] as const;

/** Stat cards: sums across adminStats(7d) days[] + quick links to admin tabs. */
export default function AdminOverview({ onNavigate }: { onNavigate: (tab: AdminTabId) => void }) {
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
      <div className="mb-4 grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(11rem,1fr))]">
        {CARDS.map((c) => (
          <Card key={c.id} testid={`stat-${c.id}`}>
            <Stat label={t(c.labelKey)} value={String(days.reduce((s, d) => s + c.sum(d), 0))} />
          </Card>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        {QUICK_LINKS.map((q) => (
          <Button key={q.tab} testid={`btn-goto-${q.tab}`} variant="secondary" size="sm" onClick={() => onNavigate(q.tab)}>
            {t(q.labelKey)}
          </Button>
        ))}
      </div>
    </div>
  );
}
