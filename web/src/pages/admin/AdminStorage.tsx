/** Lane B3 (S4): tab "Dọn dẹp dung lượng" — stats cards, bảng job cũ paged
 * (format bytes, badge purged), nút purge-due qua confirm dialog + refresh.
 * Density mirror AdminUsers (sticky thead, divider rows, mono IDs). */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "../../api/client";
import { mapApiError } from "../../lib/errors";
import { translate, useT } from "../../i18n";
import Badge from "../../components/ui/Badge";
import Button from "../../components/ui/Button";
import Card from "../../components/ui/Card";
import Skeleton from "../../components/ui/Skeleton";
import ConfirmDialog from "../../components/ConfirmDialog";

const PAGE_SIZE = 20;

/** bytes → "512 B" / "1.5 KB" / "2 MB" (1 chữ số thập phân, bỏ .0). */
export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = n;
  let i = -1;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${Math.round(v * 10) / 10} ${units[i]}`;
}

function Stat({ label, value, testid }: { label: string; value: string; testid: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span data-testid={testid} className="text-lg font-semibold tabular-nums">
        {value}
      </span>
      <span className="text-xs text-muted">{label}</span>
    </div>
  );
}

export default function AdminStorage() {
  const { t } = useT();
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const [confirm, setConfirm] = useState(false);
  const { data, isLoading } = useQuery({
    queryKey: ["admin-storage", page],
    queryFn: () => api.adminStorage(page),
  });

  const purgeDue = useMutation({
    mutationFn: api.adminStoragePurgeDue,
    onSuccess: ({ purged }) => {
      toast.success(translate("storage.purgedToast", { n: purged }));
      qc.invalidateQueries({ queryKey: ["admin-storage"] });
    },
    onError: (err) => toast.error(mapApiError(err)),
    onSettled: () => setConfirm(false),
  });

  const s = data?.stats;

  return (
    <div className="flex flex-col gap-4">
      <Card
        title={t("storage.title")}
        testid="storage-card"
        actions={
          <>
            <Button
              testid="storage-purge-due"
              variant="danger"
              size="sm"
              className="border border-error/40 bg-error/10"
              disabled={!s || s.due_jobs === 0}
              loading={purgeDue.isPending}
              onClick={() => setConfirm(true)}
            >
              <Trash2 className="h-4 w-4" aria-hidden="true" />
              {t("storage.purgeDue")}
            </Button>
            <Button
              testid="storage-refresh"
              variant="secondary"
              size="sm"
              className="min-h-11 min-w-11 p-0"
              title={t("storage.refreshAria")}
              aria-label={t("storage.refreshAria")}
              onClick={() => qc.invalidateQueries({ queryKey: ["admin-storage"] })}
            >
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
            </Button>
          </>
        }
      >
        {isLoading || !s ? (
          <Skeleton testid="storage-loading" />
        ) : (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
            <Stat testid="storage-total-jobs" label={t("storage.stats.totalJobs")} value={String(s.total_jobs)} />
            <Stat testid="storage-purged-jobs" label={t("storage.stats.purgedJobs")} value={String(s.purged_jobs)} />
            <Stat testid="storage-due-jobs" label={t("storage.stats.dueJobs")} value={String(s.due_jobs)} />
            <Stat testid="storage-total-bytes" label={t("storage.stats.totalBytes")} value={fmtBytes(s.total_upload_bytes)} />
            <Stat testid="storage-purged-bytes" label={t("storage.stats.purgedBytes")} value={fmtBytes(s.purged_bytes)} />
          </div>
        )}
      </Card>

      <Card title={t("storage.tableTitle")} testid="storage-table">
        {isLoading || !data ? (
          <Skeleton testid="storage-table-loading" />
        ) : data.items.length === 0 ? (
          <p className="py-4 text-center text-sm text-muted">{t("storage.empty")}</p>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 border-b border-border bg-surface-2 text-left text-xs text-muted">
                  <tr>
                    <th className="px-2 py-2 font-medium">#</th>
                    <th className="px-2 py-2 font-medium">{t("storage.table.email")}</th>
                    <th className="px-2 py-2 font-medium">{t("storage.table.filename")}</th>
                    <th className="px-2 py-2 font-medium">{t("storage.table.bytes")}</th>
                    <th className="px-2 py-2 font-medium">{t("storage.table.created")}</th>
                    <th className="px-2 py-2 font-medium">{t("storage.table.status")}</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((j) => (
                    <tr key={j.id} data-testid={`storage-job-${j.id}`} className="border-b border-border">
                      <td className="px-2 py-2 font-mono text-xs">{j.id}</td>
                      <td className="px-2 py-2">{j.email}</td>
                      <td className="max-w-40 truncate px-2 py-2">{j.filename ?? "—"}</td>
                      <td className="px-2 py-2 tabular-nums">{fmtBytes(j.upload_bytes)}</td>
                      <td className="px-2 py-2 font-mono text-xs">
                        {j.created_at ? new Date(j.created_at).toLocaleString(translate("i18n.locale")) : "—"}
                      </td>
                      <td className="px-2 py-2">
                        {j.storage_purged_at ? (
                          <Badge tone="neutral" testid={`purged-badge-${j.id}`}>{t("storage.purged")}</Badge>
                        ) : (
                          <Badge tone="success">{t("storage.kept")}</Badge>
                        )}
                        {!j.auto_purge && (
                          <span data-testid={`auto-off-${j.id}`} className="ml-1 text-xs text-muted">
                            {t("storage.autoOff")}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-3 flex items-center justify-end gap-2 text-sm">
              <span className="text-muted">
                {t("storage.pageInfo", { page, total: data.total })}
              </span>
              <Button
                testid="storage-prev"
                aria-label={t("storage.prevPage")}
                variant="secondary"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                ‹
              </Button>
              <Button
                testid="storage-next"
                aria-label={t("storage.nextPage")}
                variant="secondary"
                size="sm"
                disabled={page * PAGE_SIZE >= data.total}
                onClick={() => setPage((p) => p + 1)}
              >
                ›
              </Button>
            </div>
          </>
        )}
      </Card>

      <ConfirmDialog
        open={confirm}
        title={t("storage.confirmTitle")}
        message={t("storage.confirmMessage")}
        confirmLabel={t("storage.purgeDue")}
        onConfirm={() => purgeDue.mutate()}
        onCancel={() => setConfirm(false)}
      />
    </div>
  );
}
