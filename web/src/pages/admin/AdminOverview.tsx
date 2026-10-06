import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { AdminStatsDay } from "../../api/types";
import Button from "../../components/ui/Button";
import Card from "../../components/ui/Card";
import { last7Days } from "./dateRange";

export type AdminTabId = "overview" | "users" | "api" | "logs" | "stats" | "settings";

const CARDS = [
  { id: "users", label: "User mới (7 ngày)", sum: (d: AdminStatsDay) => d.users_registered },
  { id: "done", label: "Job hoàn tất", sum: (d: AdminStatsDay) => d.jobs_done },
  { id: "failed", label: "Job thất bại", sum: (d: AdminStatsDay) => d.jobs_failed },
  { id: "gpu", label: "Tổng GPU (giây)", sum: (d: AdminStatsDay) => d.gpu_seconds },
  { id: "cost", label: "Chi phí ước tính (USD)", sum: (d: AdminStatsDay) => d.estimated_cost_usd },
] as const;

const QUICK_LINKS = [
  { tab: "users", label: "Người dùng" },
  { tab: "api", label: "API" },
  { tab: "logs", label: "Logs" },
  { tab: "stats", label: "Thống kê" },
] as const;

/** Stat cards: sums across adminStats(7d) days[] + quick links to admin tabs. */
export default function AdminOverview({ onNavigate }: { onNavigate: (tab: AdminTabId) => void }) {
  const range = last7Days();
  const { data } = useQuery({
    queryKey: ["admin-stats", range.from, range.to],
    queryFn: () => api.adminStats(range.from, range.to),
  });
  const days = data?.days ?? [];

  return (
    <div>
      <div className="mb-4 grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(11rem,1fr))]">
        {CARDS.map((c) => (
          <Card key={c.id} testid={`stat-${c.id}`}>
            <p className="text-sm text-muted">{c.label}</p>
            <p className="text-2xl font-bold">{days.reduce((s, d) => s + c.sum(d), 0)}</p>
          </Card>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        {QUICK_LINKS.map((q) => (
          <Button key={q.tab} testid={`btn-goto-${q.tab}`} variant="secondary" size="sm" onClick={() => onNavigate(q.tab)}>
            {q.label}
          </Button>
        ))}
      </div>
    </div>
  );
}
