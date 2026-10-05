import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { api } from "../../api/client";
import Card from "../../components/ui/Card";

interface LogRow {
  path?: string;
  status?: number;
}

interface ApiAggRow {
  path: string;
  total: number;
  "2xx": number;
  "4xx": number;
  "5xx": number;
}

/** Normalize: numeric segments → {id}; keep at most first 3 segments (/api/jobs/{id}). */
function normalizePath(p: string): string {
  const segs = p
    .split("?")[0]
    .split("/")
    .filter(Boolean)
    .slice(0, 3)
    .map((s) => (/^\d+$/.test(s) ? "{id}" : s));
  return `/${segs.join("/")}`;
}

/** Request-log endpoint activity: client-side aggregate of last 500 request_logs rows.
 *  Rows = path × status-class (2xx/4xx/5xx) only — no method. Out-of-class statuses
 *  (1xx/3xx) are skipped so total always equals the class-count sum. */
export default function AdminApi() {
  const { data } = useQuery({
    queryKey: ["admin-api"],
    queryFn: () => api.adminLogs({ limit: 500 }),
  });

  const rows = useMemo(() => {
    const m = new Map<string, ApiAggRow>();
    for (const raw of data?.items ?? []) {
      const r = raw as LogRow;
      if (typeof r.path !== "string" || typeof r.status !== "number") continue;
      const path = normalizePath(r.path);
      const cls =
        r.status >= 200 && r.status < 300
          ? "2xx"
          : r.status >= 400 && r.status < 500
            ? "4xx"
            : r.status >= 500 && r.status < 600
              ? "5xx"
              : null;
      if (!cls) continue;
      const e = m.get(path) ?? { path, total: 0, "2xx": 0, "4xx": 0, "5xx": 0 };
      e.total += 1;
      e[cls] += 1;
      m.set(path, e);
    }
    return [...m.values()].sort((a, b) => b.total - a.total || a.path.localeCompare(b.path));
  }, [data]);

  return (
    <div>
      <p className="mb-3 text-sm text-muted">
        Tổng hợp client-side từ request_logs (500 dòng gần nhất)
      </p>
      <Card testid="api-activity-table">
        <table className="w-full border-collapse text-left text-sm">
          <thead>
            <tr className="border-b border-border text-muted">
              <th className="px-3 py-2">Path</th>
              <th className="px-3 py-2">Tổng</th>
              <th className="px-3 py-2">2xx</th>
              <th className="px-3 py-2">4xx</th>
              <th className="px-3 py-2">5xx</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.path}
                data-testid={`api-row-${r.path.replace(/[/{}]/g, "-")}`}
                className="border-b border-border/40"
              >
                <td className="px-3 py-2">{r.path}</td>
                <td className="px-3 py-2">{r.total}</td>
                <td className="px-3 py-2">{r["2xx"]}</td>
                <td className="px-3 py-2">{r["4xx"]}</td>
                <td className="px-3 py-2">{r["5xx"]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
