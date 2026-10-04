import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";

function isoDate(d: Date) {
  return d.toISOString().slice(0, 10);
}

/** Default range: last 7 days (inclusive of today). */
function last7Days() {
  const to = new Date();
  const from = new Date(to.getTime() - 6 * 24 * 60 * 60 * 1000);
  return { from: isoDate(from), to: isoDate(to) };
}

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
      <div className="mb-4 flex items-end gap-4">
        <label className="flex flex-col text-sm text-gray-500">
          Từ
          <input
            type="date"
            data-testid="input-stats-from"
            value={range.from}
            onChange={(e) => setRange((r) => ({ ...r, from: e.target.value }))}
            className="mt-1 rounded border border-gray-300 px-2 py-1"
          />
        </label>
        <label className="flex flex-col text-sm text-gray-500">
          Đến
          <input
            type="date"
            data-testid="input-stats-to"
            value={range.to}
            onChange={(e) => setRange((r) => ({ ...r, to: e.target.value }))}
            className="mt-1 rounded border border-gray-300 px-2 py-1"
          />
        </label>
      </div>
      <table className="w-full border-collapse bg-white text-left text-sm">
        <thead>
          <tr className="border-b border-gray-200 text-gray-500">
            {HEADERS.map((h) => (
              <th key={h} className="px-3 py-2">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {(data?.days ?? []).map((d) => (
            <tr key={d.date} data-testid={`stats-row-${d.date}`} className="border-b border-gray-100">
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
    </div>
  );
}
