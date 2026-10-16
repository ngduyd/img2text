import { FileText, RefreshCw } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import Badge from "../../components/ui/Badge";
import Button from "../../components/ui/Button";
import Card from "../../components/ui/Card";
import EmptyState from "../../components/ui/EmptyState";
import Input from "../../components/ui/Input";
import Skeleton from "../../components/ui/Skeleton";
import { useT } from "../../i18n";

interface LogRow {
  id: number;
  ts: string;
  method: string;
  path: string;
  status: number;
  user_id: number | null;
  ip: string;
  ua: string | null;
}

/** Status badge tone by class (DESIGN.md §2): 2xx success / 4xx warning / 5xx error. */
function statusTone(status: number): "success" | "warning" | "error" {
  return status >= 500 ? "error" : status >= 400 ? "warning" : "success";
}

/** Audit trail (request_logs): IP filter + raw log tail. Density 6 table
 * (DESIGN.md §5): sticky thead, divider rows, mono numbers (ID/IP/time), IP/UA
 * truncate + title. Testids R60/R51 kept: input-log-ip, btn-logs-refresh,
 * logs-loading/empty, audit-actor/ip/ua, logs-tail(-card). */
export default function AdminLogs() {
  const { t } = useT();
  const [ipInput, setIpInput] = useState("");
  const [ip, setIp] = useState("");

  const { data: logs, isLoading } = useQuery({
    queryKey: ["admin-logs", ip],
    queryFn: () => api.adminLogs(ip ? { ip } : {}),
  });
  const { data: tail } = useQuery({
    queryKey: ["admin-logs-tail"],
    queryFn: () => api.adminLogsTail(200),
  });

  const rows = (logs?.items ?? []) as unknown as LogRow[];

  return (
    <div className="flex flex-col gap-4">
      <Card title={t("admin.logs.title")}>
        <div className="mb-4 flex flex-wrap items-end gap-4">
          <Input
            label={t("admin.logs.ipFilter")}
            testid="input-log-ip"
            value={ipInput}
            onChange={(e) => setIpInput(e.target.value)}
            placeholder="10.0.0.1"
          />
          <Button
            testid="btn-logs-refresh"
            variant="secondary"
            size="sm"
            className="min-h-11 min-w-11 p-0"
            title={t("admin.logs.refreshAria")}
            aria-label={t("admin.logs.refreshAria")}
            onClick={() => setIp(ipInput)}
          >
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>
        {isLoading ? (
          <div data-testid="logs-loading" aria-busy="true" className="overflow-x-auto">
            <div className="min-w-[720px] divide-y divide-border">
              {[0, 1, 2].map((i) => (
                <div key={i} className="flex items-center gap-4 px-4 py-3">
                  <Skeleton className="h-5 w-20" />
                  <Skeleton className="h-4 w-24" />
                  <Skeleton className="h-4 w-32" />
                  <Skeleton className="h-4 w-16" />
                  <Skeleton className="h-4 w-40" />
                  <Skeleton className="h-5 w-12" />
                  <Skeleton className="h-4 w-28" />
                </div>
              ))}
            </div>
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            icon={FileText}
            title={t("admin.logs.emptyTitle")}
            body={t("admin.logs.emptyBody")}
            testid="logs-empty"
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] border-collapse text-left text-sm">
              <thead>
                <tr>
                  {[
                    t("admin.logs.colUser"),
                    "IP",
                    "User-Agent",
                    "Method",
                    "Path",
                    "Status",
                    t("admin.logs.colTime"),
                  ].map(
                    (h) => (
                      <th
                        key={h}
                        scope="col"
                        className="sticky top-0 z-10 border-b border-border bg-surface-2 px-4 py-3 font-medium text-muted"
                      >
                        {h}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {rows.map((row, i) => (
                  <tr
                    key={row.id ?? i}
                    className="transition-colors duration-150 ease-out hover:bg-surface-2"
                  >
                    <td data-testid="audit-actor" className="px-4 py-3">
                      <span
                        className="block max-w-[160px] truncate font-mono"
                        title={String(row.user_id ?? "")}
                      >
                        {row.user_id ?? "—"}
                      </span>
                    </td>
                    <td data-testid="audit-ip" className="px-4 py-3">
                      <span className="block max-w-[160px] truncate font-mono" title={row.ip}>
                        {row.ip}
                      </span>
                    </td>
                    <td data-testid="audit-ua" className="px-4 py-3">
                      <span className="block max-w-[160px] truncate" title={row.ua ?? ""}>
                        {row.ua}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono">
                      <Badge tone="neutral">{row.method}</Badge>
                    </td>
                    <td className="px-4 py-3 font-mono">{row.path}</td>
                    <td className="px-4 py-3 font-mono">
                      <Badge tone={statusTone(row.status)}>{row.status}</Badge>
                    </td>
                    <td className="px-4 py-3 font-mono">
                      {new Date(row.ts).toLocaleString("vi-VN")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <Card testid="logs-tail-card" title={t("admin.card.logsTail")}>
        <pre
          data-testid="logs-tail"
          className="overflow-x-auto rounded-sm border border-border bg-surface-2/60 p-3 font-mono text-xs text-muted"
        >
          {(tail?.lines ?? []).join("\n")}
        </pre>
      </Card>
    </div>
  );
}
