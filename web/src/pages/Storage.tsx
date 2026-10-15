/** Lane ST: trang /storage — user tự dọn file storage của mình (KHÔNG admin).
 * Cards + bảng lấy từ GET /api/jobs (upload_bytes, storage_purged_at — Lane M1);
 * per-job purge + bulk purge-due đều qua ConfirmDialog (R51) + toast (R59). */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2, TriangleAlert } from "lucide-react";
import { toast } from "sonner";
import { api } from "../api/client";
import { mapApiError } from "../lib/errors";
import { ageDays, sumKeptBytes } from "../lib/storage";
import { translate, useT } from "../i18n";
import Badge from "../components/ui/Badge";
import Button from "../components/ui/Button";
import Card from "../components/ui/Card";
import Skeleton from "../components/ui/Skeleton";
import ConfirmDialog from "../components/ConfirmDialog";
import { Stat, fmtBytes } from "./admin/AdminStorage";

type ConfirmState = { kind: "one"; id: number } | { kind: "due" } | null;

export default function Storage() {
  const { t } = useT();
  const qc = useQueryClient();
  const [confirm, setConfirm] = useState<ConfirmState>(null);
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["my-storage"],
    queryFn: () => api.listJobs(1, 100),
  });

  const purgeOne = useMutation({
    mutationFn: (id: number) => api.purgeJobStorage(id),
    onSuccess: () => {
      toast.success(translate("storage.own.purgedOneToast"));
      qc.invalidateQueries({ queryKey: ["my-storage"] });
    },
    onError: (err) => toast.error(mapApiError(err)),
    onSettled: () => setConfirm(null),
  });

  const purgeDue = useMutation({
    mutationFn: api.purgeMyStorageDue,
    onSuccess: ({ purged }) => {
      toast.success(translate("storage.own.purgedDueToast", { n: purged }));
      qc.invalidateQueries({ queryKey: ["my-storage"] });
    },
    onError: (err) => toast.error(mapApiError(err)),
    onSettled: () => setConfirm(null),
  });

  const items = data?.items ?? [];
  const kept = items.filter((j) => !j.storage_purged_at);
  const purgedCount = items.length - kept.length;
  const keptBytes = sumKeptBytes(kept);

  return (
    <main id="main" className="mx-auto max-w-7xl px-4 py-6">
      {/* Page header (P0-4): skip-link target + h1 + subtitle. */}
      <header className="mb-6">
        <h1 className="text-2xl font-bold tracking-tight">{t("storage.own.title")}</h1>
        <p className="mt-1 text-sm text-muted">{t("storage.own.subtitle")}</p>
      </header>
      {isError ? (
        /* P0-1: composed error + retry — thay toàn bộ body, hết skeleton vĩnh viễn. */
        <div data-testid="storage-own-error" className="flex items-start gap-3 rounded-card border border-border bg-surface p-4 shadow-card">
          <TriangleAlert className="mt-0.5 h-5 w-5 shrink-0 text-error" aria-hidden="true" />
          <div className="min-w-0">
            <p className="font-medium">{t("errors.generic")}</p>
            <p className="break-words text-sm text-muted">{mapApiError(error)}</p>
            <Button
              testid="storage-own-retry"
              variant="secondary"
              size="sm"
              className="mt-2"
              onClick={() => refetch()}
            >
              {t("common.retry")}
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <Card testid="storage-own-card">
            {isLoading || !data ? (
              <Skeleton testid="storage-own-loading" />
            ) : (
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <Stat
                  testid="storage-own-kept-files"
                  label={t("storage.own.stats.keptFiles")}
                  value={String(kept.length)}
                />
                <Stat
                  testid="storage-own-purged-files"
                  label={t("storage.own.stats.purgedFiles")}
                  value={String(purgedCount)}
                />
                <Stat
                  testid="storage-own-kept-bytes"
                  label={t("storage.own.stats.keptBytes")}
                  value={fmtBytes(keptBytes)}
                />
              </div>
            )}
          </Card>

          <Card
            title={t("storage.own.tableTitle")}
            testid="storage-own-table"
            actions={
              <Button
                testid="storage-own-purge-due"
                variant="danger"
                size="sm"
                className="border border-error/40 bg-error/10"
                disabled={!data || items.length === 0}
                loading={purgeDue.isPending}
                onClick={() => setConfirm({ kind: "due" })}
              >
                <Trash2 className="h-4 w-4" aria-hidden="true" />
                {t("storage.own.purgeDue")}
              </Button>
            }
          >
            {isLoading || !data ? (
              <Skeleton testid="storage-own-table-loading" />
            ) : items.length === 0 ? (
              <p className="py-4 text-center text-sm text-muted">{t("storage.own.empty")}</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 border-b border-border bg-surface-2 text-left text-xs text-muted">
                    <tr>
                      <th className="px-2 py-2 font-medium">{t("storage.own.table.filename")}</th>
                      <th className="px-2 py-2 font-medium">{t("storage.own.table.created")}</th>
                      <th className="px-2 py-2 font-medium">{t("storage.own.table.age")}</th>
                      <th className="px-2 py-2 font-medium">{t("storage.own.table.size")}</th>
                      <th className="px-2 py-2 font-medium">{t("storage.own.table.status")}</th>
                      <th className="px-2 py-2">
                        <span className="sr-only">{t("storage.own.table.actions")}</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((j) => (
                      <tr key={j.id} data-testid={`storage-own-job-${j.id}`} className="border-b border-border">
                        <td className="max-w-40 truncate px-2 py-2">{j.filename ?? "—"}</td>
                        <td className="px-2 py-2 font-mono text-xs">
                          {j.created_at
                            ? new Date(j.created_at).toLocaleString(translate("i18n.locale"))
                            : "—"}
                        </td>
                        <td className="px-2 py-2 tabular-nums">
                          {translate("storage.own.ageDays", { n: ageDays(j.created_at) })}
                        </td>
                        <td className="px-2 py-2 tabular-nums">{fmtBytes(j.upload_bytes || 0)}</td>
                        <td className="px-2 py-2">
                          {j.storage_purged_at ? (
                            <Badge tone="neutral" testid={`purged-badge-${j.id}`}>
                              {t("storage.purged")}
                            </Badge>
                          ) : (
                            <Badge tone="success">{t("storage.kept")}</Badge>
                          )}
                        </td>
                        <td className="px-2 py-2 text-right">
                          {!j.storage_purged_at && (
                            <Button
                              testid={`storage-purge-${j.id}`}
                              variant="danger"
                              size="sm"
                              className="border border-error/40 bg-error/10"
                              loading={purgeOne.isPending && confirm?.kind === "one" && confirm.id === j.id}
                              onClick={() => setConfirm({ kind: "one", id: j.id })}
                            >
                              <Trash2 className="h-4 w-4" aria-hidden="true" />
                              {t("storage.own.purgeOne")}
                            </Button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          {confirm && (
            <ConfirmDialog
              open
              title={
                confirm.kind === "one"
                  ? t("storage.own.confirmOneTitle")
                  : t("storage.own.confirmDueTitle")
              }
              message={
                confirm.kind === "one"
                  ? t("storage.own.confirmOneMessage")
                  : t("storage.own.confirmDueMessage")
              }
              confirmLabel={
                confirm.kind === "one" ? t("storage.own.purgeOne") : t("storage.own.purgeDue")
              }
              onConfirm={() =>
                confirm.kind === "one" ? purgeOne.mutate(confirm.id) : purgeDue.mutate()
              }
              onCancel={() => setConfirm(null)}
            />
          )}
        </div>
      )}
    </main>
  );
}
