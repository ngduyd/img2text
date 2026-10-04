import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";

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
      <div className="mb-4 flex items-end gap-4">
        <label className="flex flex-col text-sm text-gray-500">
          Lọc theo IP
          <input
            type="text"
            data-testid="input-log-ip"
            value={ipInput}
            onChange={(e) => setIpInput(e.target.value)}
            placeholder="10.0.0.1"
            className="mt-1 rounded border border-gray-300 px-2 py-1"
          />
        </label>
        <button
          data-testid="btn-logs-refresh"
          onClick={() => setIp(ipInput)}
          className="rounded bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
        >
          Làm mới
        </button>
      </div>
      <table className="w-full border-collapse bg-white text-left text-sm">
        <thead>
          <tr className="border-b border-gray-200 text-gray-500">
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
              <tr key={row.id ?? i} className="border-b border-gray-100">
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
      <pre data-testid="logs-tail" className="mt-4 overflow-x-auto rounded border border-gray-200 bg-gray-900 p-3 text-xs text-gray-100">
        {(tail?.lines ?? []).join("\n")}
      </pre>
    </div>
  );
}
