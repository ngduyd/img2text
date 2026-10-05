import { RefreshCw } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import Button from "../../components/ui/Button";
import Card from "../../components/ui/Card";
import Input from "../../components/ui/Input";

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

/** Audit trail (request_logs): actor + IP filter (refresh click) + raw log tail.
 * Plan X R60: actor (user_id) + IP + User-Agent columns, truncated 160px,
 * title = full value; missing user_id renders "—". */
export default function AdminLogs() {
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
      <Card title="Nhật ký truy cập">
        <div className="mb-4 flex flex-wrap items-end gap-4">
          <Input
            label="Lọc theo IP"
            testid="input-log-ip"
            value={ipInput}
            onChange={(e) => setIpInput(e.target.value)}
            placeholder="10.0.0.1"
          />
          <Button
            testid="btn-logs-refresh"
            variant="secondary"
            size="sm"
            className="p-2"
            title="Làm mới danh sách nhật ký"
            aria-label="Làm mới danh sách nhật ký"
            onClick={() => setIp(ipInput)}
          >
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
          </Button>
        </div>
        {isLoading ? (
          <div data-testid="logs-loading" className="p-8 text-center text-muted">
            Đang tải…
          </div>
        ) : rows.length === 0 ? (
          <div data-testid="logs-empty" className="p-8 text-center text-muted">
            Chưa có nhật ký
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-border text-muted">
                  {["Method", "Người dùng", "Path", "Status", "IP", "User-Agent", "Thời gian"].map((h) => (
                    <th
                      key={h}
                      scope="col"
                      className="sticky top-0 bg-surface px-4 py-3 font-medium"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr
                    key={row.id ?? i}
                    className="border-b border-border/40 odd:bg-bg/60"
                  >
                    <td className="px-4 py-3">{row.method}</td>
                    <td data-testid="audit-actor" className="px-4 py-3">
                      <span
                        className="block max-w-[160px] truncate"
                        title={String(row.user_id ?? "")}
                      >
                        {row.user_id ?? "—"}
                      </span>
                    </td>
                    <td className="px-4 py-3">{row.path}</td>
                    <td className="px-4 py-3">{row.status}</td>
                    <td data-testid="audit-ip" className="px-4 py-3">
                      <span className="block max-w-[160px] truncate" title={row.ip}>
                        {row.ip}
                      </span>
                    </td>
                    <td data-testid="audit-ua" className="px-4 py-3">
                      <span className="block max-w-[160px] truncate" title={row.ua ?? ""}>
                        {row.ua}
                      </span>
                    </td>
                    <td className="px-4 py-3">{row.ts}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      <Card testid="logs-tail-card" title="Log tail">
        <pre
          data-testid="logs-tail"
          className="overflow-x-auto rounded-card border border-border bg-surface p-3 text-xs text-muted"
        >
          {(tail?.lines ?? []).join("\n")}
        </pre>
      </Card>
    </div>
  );
}
