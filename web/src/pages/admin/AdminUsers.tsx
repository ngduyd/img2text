import { ScanText, Users } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "../../api/client";
import { mapApiError } from "../../lib/errors";
import type { User } from "../../api/types";
import Badge from "../../components/ui/Badge";
import Card from "../../components/ui/Card";
import Skeleton from "../../components/ui/Skeleton";

/** Admin user list — DESIGN.md §5 density 6: sticky thead (surface-2 + border-b),
 * divider rows (no zebra), mono IDs/dates, role badge, icon OCR toggle (44px,
 * title + aria). Testids R51: users-loading/empty, user-row-*, role-badge-*, toggle-ocr-*. */
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
        <div data-testid="users-loading" aria-busy="true" className="overflow-x-auto">
          <div className="min-w-[560px] divide-y divide-border">
            {[0, 1, 2].map((i) => (
              <div key={i} className="flex items-center gap-4 px-4 py-3">
                <Skeleton className="h-4 w-8" />
                <Skeleton className="h-4 w-48" />
                <Skeleton className="h-5 w-16" />
                <Skeleton className="h-4 w-28" />
                <Skeleton className="h-11 w-11" />
              </div>
            ))}
          </div>
        </div>
      ) : items.length === 0 ? (
        <div
          data-testid="users-empty"
          className="flex flex-col items-center gap-2 px-4 py-8 text-center"
        >
          <Users className="h-8 w-8 text-muted" aria-hidden="true" />
          <p className="text-base font-semibold">Chưa có người dùng</p>
          <p className="text-sm text-muted">
            Người dùng mới sẽ xuất hiện tại đây sau khi đăng ký.
          </p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] border-collapse text-left text-sm">
            <thead>
              <tr>
                {["ID", "Email", "Vai trò", "Ngày tạo", "OCR"].map((h) => (
                  <th
                    key={h}
                    scope="col"
                    className="sticky top-0 z-10 border-b border-border bg-surface-2 px-4 py-3 font-medium text-muted"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {items.map((u: User) => {
                const on = u.ocr_enabled;
                return (
                  <tr
                    key={u.id}
                    data-testid={`user-row-${u.id}`}
                    className="transition-colors duration-150 ease-out hover:bg-surface-2"
                  >
                    <td className="px-4 py-3 font-mono">{u.id}</td>
                    <td className="px-4 py-3">{u.email}</td>
                    <td className="px-4 py-3">
                      <Badge
                        testid={`role-badge-${u.id}`}
                        tone={u.role === "admin" ? "info" : "neutral"}
                      >
                        {u.role}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 font-mono">
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
                        className={`inline-flex min-h-11 min-w-11 cursor-pointer items-center justify-center rounded-md border transition duration-150 ease-out active:-translate-y-px ${
                          on
                            ? "border-accent/40 bg-accent/10 text-accent-text"
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
