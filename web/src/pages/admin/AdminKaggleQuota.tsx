import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { api } from "../../api/client";
import { translate, useT } from "../../i18n";
import Button from "../../components/ui/Button";
import Card from "../../components/ui/Card";
import Skeleton from "../../components/ui/Skeleton";

/** Giây → "6h" / "1h 38m" / "38m" (bỏ phần phút 0). */
export function fmtDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h === 0) return `${m}m`;
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

function fmtRefresh(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(translate("i18n.locale"));
}

/**
 * Admin card "GPU/Kaggle Quota" — GET /api/admin/kaggle-quota (Lane K).
 * Loading skeleton text + lỗi (503 thiếu package / 502 Kaggle API) hiển thị inline.
 */
export default function AdminKaggleQuota() {
  const { t } = useT();
  const { data, isPending, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["admin-kaggle-quota"],
    queryFn: api.getKaggleQuota,
    retry: false,
  });

  return (
    <Card
      title={t("admin.card.kaggleQuota")}
      testid="kaggle-quota"
      actions={
        <Button
          testid="kaggle-quota-refresh"
          variant="secondary"
          size="sm"
          className="min-h-11 min-w-11 p-0"
          title={t("admin.kaggle.refreshAria")}
          aria-label={t("admin.kaggle.refreshAria")}
          loading={isFetching}
          onClick={() => refetch()}
        >
          <RefreshCw className="h-4 w-4" aria-hidden="true" />
        </Button>
      }
    >
      {isPending ? (
        <Skeleton testid="kaggle-quota-loading" />
      ) : isError ? (
        // ApiError.detail (503/502 body) — không instanceof (module có thể mock)
        <p data-testid="kaggle-quota-error" role="alert" className="text-sm text-error">
          {(error as { detail?: string } | undefined)?.detail ?? String(error)}
        </p>
      ) : (
        <div className="flex flex-col gap-1 text-sm">
          <p data-testid="kaggle-quota-gpu">
            {t("admin.kaggle.gpu", {
              used: fmtDuration(data.gpu.used_s),
              total: fmtDuration(data.gpu.total_s),
              remaining: fmtDuration(data.gpu.remaining_s),
            })}
          </p>
          <p data-testid="kaggle-quota-tpu">
            {t("admin.kaggle.tpu", {
              used: fmtDuration(data.tpu.used_s),
              total: fmtDuration(data.tpu.total_s),
            })}
          </p>
          <p data-testid="kaggle-quota-refresh-time" className="text-muted">
            {t("admin.kaggle.refreshAt", { time: fmtRefresh(data.gpu.refresh) })}
          </p>
        </div>
      )}
    </Card>
  );
}
