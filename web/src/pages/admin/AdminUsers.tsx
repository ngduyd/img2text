import { ScanText } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "../../api/client";
import { mapApiError } from "../../lib/errors";
import type { User } from "../../api/types";
import Badge from "../../components/ui/Badge";
import Card from "../../components/ui/Card";

/** Admin user list: role badge + per-user OCR grant toggle (icon button,
 * ui-ux skill: tokens, sticky thead, title tooltips, 320px overflow-x). */
export default function AdminUsers() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["admin-users"], queryFn: () => api.adminListUsers(1) });

  const patchUser = useMutation({
    mutationFn: (vars: { id: number; ocr_enabled: boolean }) =>
      api.adminPatchUser(vars.id, { ocr_enabled: vars.ocr_enabled }),
    onSuccess: () => {
      toast.success("Đã cập nhật.");
      qc.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: (err) => toast.error(mapApiError(err)),
  });

  const items = data?.items ?? [];

  return (
    <Card title="Người dùng">
      {isLoading ? (
        <div data-testid="users-loading" className="p-8 text-center text-muted">
          Đang tải…
        </div>
      ) : items.length === 0 ? (
        <div data-testid="users-empty" className="p-8 text-center text-muted">
          Chưa có người dùng
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-border text-muted">
                {["ID", "Email", "Vai trò", "Ngày tạo", "OCR"].map((h) => (
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
              {items.map((u: User) => {
                const on = u.ocr_enabled;
                return (
                  <tr key={u.id} data-testid={`user-row-${u.id}`} className="border-b border-border/40 odd:bg-bg/60">
                    <td className="px-4 py-3">{u.id}</td>
                    <td className="px-4 py-3">{u.email}</td>
                    <td className="px-4 py-3">
                      <Badge
                        testid={`role-badge-${u.id}`}
                        tone={u.role === "admin" ? "info" : "neutral"}
                      >
                        {u.role}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      {u.created_at ? new Date(u.created_at).toLocaleDateString("vi-VN") : ""}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        type="button"
                        data-testid={`toggle-ocr-${u.id}`}
                        aria-pressed={on}
                        aria-label={`OCR ${u.email}`}
                        title={`${on ? "Tắt" : "Bật"} OCR cho ${u.email}`}
                        onClick={() => patchUser.mutate({ id: u.id, ocr_enabled: !on })}
                        className={`inline-flex min-h-10 min-w-10 cursor-pointer items-center justify-center rounded-lg border transition-opacity hover:opacity-90 ${
                          on
                            ? "border-accent/40 bg-accent/10 text-accent"
                            : "border-border bg-surface text-muted"
                        }`}
                      >
                        <ScanText className="h-4 w-4" aria-hidden="true" />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
