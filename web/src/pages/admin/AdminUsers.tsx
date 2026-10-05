import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";
import type { User } from "../../api/types";
import Badge from "../../components/ui/Badge";
import Card from "../../components/ui/Card";

/** User list with per-user OCR grant toggle + created_at (vi-VN). */
export default function AdminUsers() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["admin-users"], queryFn: () => api.adminListUsers(1) });

  const patchUser = useMutation({
    mutationFn: (vars: { id: number; ocr_enabled: boolean }) =>
      api.adminPatchUser(vars.id, { ocr_enabled: vars.ocr_enabled }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }),
  });

  return (
    <Card title="Người dùng">
      <table className="w-full border-collapse text-left">
        <thead>
          <tr className="border-b border-border text-sm text-muted">
            <th className="px-3 py-2">ID</th>
            <th className="px-3 py-2">Email</th>
            <th className="px-3 py-2">Vai trò</th>
            <th className="px-3 py-2">Ngày tạo</th>
            <th className="px-3 py-2">OCR</th>
          </tr>
        </thead>
        <tbody>
          {(data?.items ?? []).map((u: User) => (
            <tr key={u.id} data-testid={`user-row-${u.id}`} className="border-b border-border/40">
              <td className="px-3 py-2">{u.id}</td>
              <td className="px-3 py-2">{u.email}</td>
              <td className="px-3 py-2">
                <Badge tone={u.role === "admin" ? "info" : "neutral"}>{u.role}</Badge>
              </td>
              <td className="px-3 py-2">
                {u.created_at ? new Date(u.created_at).toLocaleDateString("vi-VN") : ""}
              </td>
              <td className="px-3 py-2">
                <input
                  type="checkbox"
                  data-testid={`toggle-ocr-${u.id}`}
                  defaultChecked={u.ocr_enabled}
                  aria-label={`OCR ${u.email}`}
                  onChange={(e) =>
                    patchUser.mutate({ id: u.id, ocr_enabled: e.target.checked })
                  }
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
