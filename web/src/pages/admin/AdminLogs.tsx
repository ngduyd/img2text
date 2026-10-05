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
  ip: string;
}

/** Request log list with IP filter (applied on refresh click) + raw tail. */
export default function AdminLogs() {
  const [ipInput, setIpInput] = useState("");
  const [ip, setIp] = useState("");

  const { data: logs } = useQuery({
    queryKey: ["admin-logs", ip],
    queryFn: () => api.adminLogs(ip ? { ip } : {}),
  });
  const { data: tail } = useQuery({
    queryKey: ["admin-logs-tail"],
    queryFn: () => api.adminLogsTail(200),
  });

  return (
    <div>
      <Card>
        <div className="mb-4 flex items-end gap-4">
          <Input
            label="Lọc theo IP"
            testid="input-log-ip"
            value={ipInput}
            onChange={(e) => setIpInput(e.target.value)}
            placeholder="10.0.0.1"
          />
          <Button testid="btn-logs-refresh" size="sm" onClick={() => setIp(ipInput)}>
            Làm mới
          </Button>
        </div>
        <table className="w-full border-collapse text-left text-sm">
          <thead>
            <tr className="border-b border-border text-muted">
              <th className="px-3 py-2">Method</th>
              <th className="px-3 py-2">Path</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">IP</th>
              <th className="px-3 py-2">Thời gian</th>
            </tr>
          </thead>
          <tbody>
            {(logs?.items ?? []).map((r, i) => {
              const row = r as unknown as LogRow;
              return (
                <tr key={row.id ?? i} className="border-b border-border/40">
                  <td className="px-3 py-2">{row.method}</td>
                  <td className="px-3 py-2">{row.path}</td>
                  <td className="px-3 py-2">{row.status}</td>
                  <td className="px-3 py-2">{row.ip}</td>
                  <td className="px-3 py-2">{row.ts}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
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
