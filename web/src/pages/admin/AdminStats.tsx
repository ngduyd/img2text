import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import Card from "../../components/ui/Card";
import Input from "../../components/ui/Input";
import { useT } from "../../i18n";
import { last7Days } from "./dateRange";

const HEADERS = [
  "admin.stats.date",
  "admin.stats.registered",
  "admin.stats.jobs",
  "admin.stats.done",
  "admin.stats.failed",
  "admin.stats.views",
  "admin.stats.emailsSent",
  "admin.stats.emailsFailed",
  "admin.stats.gpu",
  "admin.stats.cost",
] as const;

/** Daily admin stats with from/to date filters. */
export default function AdminStats() {
  const { t } = useT();
  const [range, setRange] = useState(last7Days);
  const { data } = useQuery({
    queryKey: ["admin-stats", range.from, range.to],
    queryFn: () => api.adminStats(range.from, range.to),
  });

  return (
    <div>
      <Card>
        <div className="mb-4 flex items-end gap-4">
          <Input
            label={t("admin.stats.from")}
            testid="input-stats-from"
            type="date"
            value={range.from}
            onChange={(e) => setRange((r) => ({ ...r, from: e.target.value }))}
          />
          <Input
            label={t("admin.stats.to")}
            testid="input-stats-to"
            type="date"
            value={range.to}
            onChange={(e) => setRange((r) => ({ ...r, to: e.target.value }))}
          />
        </div>
        <div className="overflow-x-auto">
        <table className="w-full border-collapse text-left text-sm">
          <thead>
            <tr>
              {HEADERS.map((h) => (
                <th key={h} scope="col" className="sticky top-0 z-10 border-b border-border bg-surface-2 px-3 py-2 font-medium text-muted">
                  {t(h)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(data?.days ?? []).map((d) => (
              <tr key={d.date} data-testid={`stats-row-${d.date}`} className="border-b border-border/40">
                <td className="px-3 py-2 font-mono tabular-nums">{d.date}</td>
                <td className="px-3 py-2 font-mono tabular-nums">{d.users_registered}</td>
                <td className="px-3 py-2 font-mono tabular-nums">{d.jobs_submitted}</td>
                <td className="px-3 py-2 font-mono tabular-nums">{d.jobs_done}</td>
                <td className="px-3 py-2 font-mono tabular-nums">{d.jobs_failed}</td>
                <td className="px-3 py-2 font-mono tabular-nums">{d.page_views}</td>
                <td className="px-3 py-2 font-mono tabular-nums">{d.emails_sent}</td>
                <td className="px-3 py-2 font-mono tabular-nums">{d.emails_failed}</td>
                <td className="px-3 py-2 font-mono tabular-nums">{d.gpu_seconds}</td>
                <td className="px-3 py-2 font-mono tabular-nums">{d.estimated_cost_usd}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </Card>
    </div>
  );
}
