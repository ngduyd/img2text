import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useT } from "../i18n";

/** WS-ADMIN T6: "Còn X trang hôm nay · Y tuần này" — Jobs header.
 * 401/403 → api.getMyQuota trả null → ẩn widget (không redirect). */
export default function QuotaBadge() {
  const { t } = useT();
  const { data } = useQuery({
    queryKey: ["quota"],
    queryFn: api.getMyQuota,
    retry: false,
  });
  if (!data) return null;
  return (
    <p data-testid="quota-remaining" className="mt-1 text-sm text-muted">
      {t("quota.remaining", {
        dUsed: data.daily_remaining,
        dLimit: data.daily_limit,
        wUsed: data.weekly_remaining,
        wLimit: data.weekly_limit,
      })}
    </p>
  );
}
