import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { translate, useT } from "../../i18n";
import Badge from "../../components/ui/Badge";
import Card from "../../components/ui/Card";

/** Spec #7: 2 lease × 45p = 2700s → worker im lặng quá ngưỡng → badge amber. */
const SILENT_THRESHOLD = 2700;

function fmt(iso: string): string {
  return new Date(iso).toLocaleString(translate("i18n.locale"));
}

/**
 * Admin card "Workers" — poll 30s GET /api/admin/workers.
 * 403/401 (ApiError) → ẩn card (không phải admin / session hết).
 */
export default function AdminWorkers() {
  const { t } = useT();
  const { data, isError } = useQuery({
    queryKey: ["admin-workers"],
    queryFn: api.getWorkers,
    refetchInterval: 30000,
    retry: false,
  });
  if (isError || !data) return null;

  return (
    <Card testid="admin-workers" title={t("admin.card.workers")} >
      <p className="mb-2 text-sm text-muted">
        {t("admin.workers.queue")}{" "}
        <span data-testid="queue-depth" className="font-mono font-semibold text-text">
          {data.queue_depth}
        </span>
      </p>
      {data.items.length === 0 ? (
        <p className="text-sm text-muted">{t("admin.workers.empty")}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {data.items.map((w) => {
            const silent = w.silent_seconds > SILENT_THRESHOLD;
            return (
              <li
                key={w.worker_id}
                data-testid={`worker-row-${w.worker_id}`}
                className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-2 text-sm last:border-0 last:pb-0"
              >
                <span className="flex flex-wrap items-center gap-2">
                  <Badge tone="info">{w.kind}</Badge>
                  <span className="font-mono text-muted">{w.worker_id}</span>
                  <span className="text-muted">last_seen {fmt(w.last_seen)}</span>
                  {w.current_job_id !== null && (
                    <span className="text-muted">job #{w.current_job_id}</span>
                  )}
                </span>
                {silent && (
                  <Badge testid={`worker-silent-${w.worker_id}`} tone="warning">
                    {t("admin.workers.silent", { s: w.silent_seconds })}
                  </Badge>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
