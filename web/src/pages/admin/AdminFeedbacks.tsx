import { MessageSquare } from "lucide-react";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { translate, useT } from "../../i18n";
import Button from "../../components/ui/Button";
import Card from "../../components/ui/Card";
import Skeleton from "../../components/ui/Skeleton";

const PAGE_SIZE = 20;

/** Lane B2 (wave-5 S6): admin feedbacks list — content/email/page/date, pagination. */
export default function AdminFeedbacks() {
  const { t } = useT();
  const [page, setPage] = useState(1);
  const { data, isLoading } = useQuery({
    queryKey: ["admin-feedbacks", page],
    queryFn: () => api.adminListFeedbacks(page, PAGE_SIZE),
  });

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <Card
      title={t("admin.tab.feedbacks")}
      testid="card-feedbacks"
      actions={
        <span data-testid="fb-total" className="self-center text-sm text-muted">
          {t("admin.feedbacks.total", { n: total })}
        </span>
      }
    >
      {isLoading ? (
        <Skeleton testid="fb-loading" />
      ) : items.length === 0 ? (
        <div
          data-testid="fb-empty"
          className="flex flex-col items-center gap-2 px-4 py-8 text-center"
        >
          <MessageSquare className="h-8 w-8 text-muted" aria-hidden="true" />
          <p className="text-sm text-muted">{t("admin.feedbacks.empty")}</p>
        </div>
      ) : (
        <ul className="divide-y divide-border">
          {items.map((fb) => (
            <li
              key={fb.id}
              data-testid={`fb-row-${fb.id}`}
              className="flex flex-col gap-1 py-3"
            >
              <p className="whitespace-pre-wrap break-words text-sm">{fb.content}</p>
              <p className="font-mono text-xs text-muted">
                {fb.email ?? t("admin.feedbacks.anonymous")} · {fb.page_path ?? "—"} ·{" "}
                {fb.created_at
                  ? new Date(fb.created_at).toLocaleString(translate("i18n.locale"))
                  : ""}
              </p>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-3 flex items-center justify-end gap-2">
        <Button
          type="button"
          testid="fb-prev"
          size="sm"
          variant="ghost"
          disabled={page <= 1}
          onClick={() => setPage((p) => p - 1)}
        >
          {t("jobs.prev")}
        </Button>
        <span className="text-sm text-muted">
          {t("admin.feedbacks.page", { page, pages })}
        </span>
        <Button
          type="button"
          testid="fb-next"
          size="sm"
          variant="ghost"
          disabled={page >= pages}
          onClick={() => setPage((p) => p + 1)}
        >
          {t("jobs.next")}
        </Button>
      </div>
    </Card>
  );
}
