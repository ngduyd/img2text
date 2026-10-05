import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import Card from "../../components/ui/Card";
import Input from "../../components/ui/Input";
import { last7Days } from "./dateRange";

const HEADERS = [
  "Ngày",
  "Đăng ký",
  "Job",
  "Hoàn tất",
  "Thất bại",
  "Lượt xem",
  "GPU (giây)",
  "Chi phí ước tính",
] as const;

/** Daily admin stats with from/to date filters. */
export default function AdminStats() {
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
            label="Từ"
            testid="input-stats-from"
            type="date"
            value={range.from}
            onChange={(e) => setRange((r) => ({ ...r, from: e.target.value }))}
          />
          <Input
            label="Đến"
            testid="input-stats-to"
            type="date"
            value={range.to}
            onChange={(e) => setRange((r) => ({ ...r, to: e.target.value }))}
          />
        </div>
        <table className="w-full border-collapse text-left text-sm">
          <thead>
            <tr className="border-b border-border text-muted">
              {HEADERS.map((h) => (
                <th key={h} className="px-3 py-2">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {(data?.days ?? []).map((d) => (
              <tr key={d.date} data-testid={`stats-row-${d.date}`} className="border-b border-border/40">
                <td className="px-3 py-2">{d.date}</td>
                <td className="px-3 py-2">{d.users_registered}</td>
                <td className="px-3 py-2">{d.jobs_submitted}</td>
                <td className="px-3 py-2">{d.jobs_done}</td>
                <td className="px-3 py-2">{d.jobs_failed}</td>
                <td className="px-3 py-2">{d.page_views}</td>
                <td className="px-3 py-2">{d.gpu_seconds}</td>
                <td className="px-3 py-2">{d.estimated_cost_usd}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
