import { ScanText, Users } from "lucide-react";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "../../api/client";
import { mapApiError } from "../../lib/errors";
import { translate, useT } from "../../i18n";
import type { User } from "../../api/types";
import Badge from "../../components/ui/Badge";
import Button from "../../components/ui/Button";
import Card from "../../components/ui/Card";
import EmptyState from "../../components/ui/EmptyState";
import Input from "../../components/ui/Input";
import Skeleton from "../../components/ui/Skeleton";

/** Admin user list — DESIGN.md §5 density 6: sticky thead (surface-2 + border-b),
 * divider rows (no zebra), mono IDs/dates, role badge, icon OCR toggle (44px,
 * title + aria). Testids R51: users-loading/empty, user-row-*, role-badge-*, toggle-ocr-*. */
export default function AdminUsers() {
  const { t } = useT();
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["admin-users"], queryFn: () => api.adminListUsers(1) });

  const patchUser = useMutation({
    mutationFn: (vars: { id: number; ocr_enabled: boolean }) =>
      api.adminPatchUser(vars.id, { ocr_enabled: vars.ocr_enabled }),
    onSuccess: () => {
      toast.success(translate("admin.users.updated"));
      qc.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: (err) => toast.error(mapApiError(err)),
  });

  // WS-ADMIN T5: inline edit 2 limit (0–10000 — mirror server 422)
  const patchQuota = useMutation({
    mutationFn: (vars: { id: number; daily: number; weekly: number }) =>
      api.adminPatchQuota(vars.id, {
        daily_page_limit: vars.daily,
        weekly_page_limit: vars.weekly,
      }),
    onSuccess: (_data, vars) => {
      toast.success(translate("editor.saved"));
      setDrafts(({ [vars.id]: _drop, ...rest }) => rest);
      setErrors(({ [vars.id]: _drop, ...rest }) => rest);
      qc.invalidateQueries({ queryKey: ["admin-users"] });
    },
    onError: (err) => toast.error(mapApiError(err)),
  });

  // Review R1 P2: controlled inputs (bỏ getElementById), field error theo row,
  // spin chỉ row đang lưu (pendingUserId thay vì isPending chung).
  const [drafts, setDrafts] = useState<Record<number, { daily: string; weekly: string }>>({});
  const [errors, setErrors] = useState<Record<number, string>>({});
  const [pendingUserId, setPendingUserId] = useState<number | null>(null);

  function saveQuota(u: User) {
    const draft = drafts[u.id];
    const read = (field: "daily" | "weekly", fallback: number | null | undefined): number | null => {
      const raw = (draft?.[field] ?? String(fallback ?? "")).trim();
      return /^\d+$/.test(raw) ? Number(raw) : null;
    };
    const daily = read("daily", u.daily_limit);
    const weekly = read("weekly", u.weekly_limit);
    if (daily === null || weekly === null || daily > 10000 || weekly > 10000) {
      setErrors((e) => ({
        ...e,
        [u.id]: t("admin.users.quotaInvalid"),
      }));
      return;
    }
    setErrors(({ [u.id]: _drop, ...rest }) => rest);
    setPendingUserId(u.id);
    patchQuota.mutate(
      { id: u.id, daily, weekly },
      { onSettled: () => setPendingUserId(null) },
    );
  }

  const items = data?.items ?? [];

  return (
    <Card title={t("admin.tab.users")}>
      {isLoading ? (
        <div data-testid="users-loading" aria-busy="true" className="overflow-x-auto">
          <div className="min-w-[760px] divide-y divide-border">
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
        <EmptyState
          icon={Users}
          title={t("admin.users.emptyTitle")}
          body={t("admin.users.emptyBody")}
          testid="users-empty"
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] border-collapse text-left text-sm">
            <thead>
              <tr>
                {[
                  t("admin.users.colId"),
                  t("admin.users.colEmail"),
                  t("admin.users.colRole"),
                  t("admin.users.colCreated"),
                  t("admin.users.colQuota"),
                  "OCR",
                ].map((h) => (
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
                      {u.created_at ? new Date(u.created_at).toLocaleDateString(translate("i18n.locale")) : ""}
                    </td>
                    <td className="px-4 py-3" data-testid={`quota-${u.id}`}>
                      <div className="flex flex-wrap items-end gap-2">
                        <div className="font-mono text-xs leading-tight">
                          <div data-testid={`quota-daily-${u.id}`}>
                            {t("admin.users.quotaDaily", {
                              used: u.daily_used ?? "",
                              limit: u.daily_limit ?? "",
                              remaining: u.daily_remaining ?? "",
                            })}
                          </div>
                          <div data-testid={`quota-weekly-${u.id}`} className="text-muted">
                            {t("admin.users.quotaWeekly", {
                              used: u.weekly_used ?? "",
                              limit: u.weekly_limit ?? "",
                              remaining: u.weekly_remaining ?? "",
                            })}
                          </div>
                        </div>
                        <Input
                          label={t("admin.users.colDaily")}
                          testid={`daily-limit-${u.id}`}
                          name={`daily-limit-${u.id}`}
                          type="number"
                          min={0}
                          max={10000}
                          value={drafts[u.id]?.daily ?? String(u.daily_limit ?? "")}
                          error={errors[u.id]}
                          onChange={(e) =>
                            setDrafts((d) => ({
                              ...d,
                              [u.id]: { ...d[u.id], daily: e.target.value, weekly: d[u.id]?.weekly ?? String(u.weekly_limit ?? "") },
                            }))
                          }
                          className="w-20"
                        />
                        <Input
                          label={t("admin.users.colWeekly")}
                          testid={`weekly-limit-${u.id}`}
                          name={`weekly-limit-${u.id}`}
                          type="number"
                          min={0}
                          max={10000}
                          value={drafts[u.id]?.weekly ?? String(u.weekly_limit ?? "")}
                          error={errors[u.id]}
                          onChange={(e) =>
                            setDrafts((d) => ({
                              ...d,
                              [u.id]: { daily: d[u.id]?.daily ?? String(u.daily_limit ?? ""), weekly: e.target.value },
                            }))
                          }
                          className="w-20"
                        />
                        <Button
                          type="button"
                          testid={`save-quota-${u.id}`}
                          onClick={() => saveQuota(u)}
                          loading={patchQuota.isPending && pendingUserId === u.id}
                        >
                          {t("admin.users.saveQuota")}
                        </Button>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <button
                        type="button"
                        data-testid={`toggle-ocr-${u.id}`}
                        aria-pressed={on}
                        aria-label={`OCR ${u.email}`}
                        title={t(on ? "admin.users.ocrOff" : "admin.users.ocrOn", { email: u.email })}
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
