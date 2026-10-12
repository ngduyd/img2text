import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

/** WS-ADMIN T6: "Còn X trang hôm nay · Y tuần này" — Jobs header.
 * 401/403 → api.getMyQuota trả null → ẩn widget (không redirect). */
export default function QuotaBadge() {
  const { data } = useQuery({
    queryKey: ["quota"],
    queryFn: api.getMyQuota,
    retry: false,
  });
  if (!data) return null;
  return (
    <p data-testid="quota-remaining" className="mt-1 text-sm text-muted">
      Còn {data.daily_remaining} trang hôm nay · {data.weekly_remaining} tuần này
    </p>
  );
}
