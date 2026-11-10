import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { useT } from "../i18n";

/** Nút đăng nhập ngoài (Google). Server tắt OAuth (thiếu client id/secret) thì
 *  không render gì — không hiện nút bấm ra 501. Điều hướng cả trang (không XHR)
 *  vì luồng này là redirect qua Google rồi quay lại /jobs kèm cookie. */
export default function OAuthButtons({ divider = true }: { divider?: boolean }) {
  const { t } = useT();
  const { data } = useQuery({
    queryKey: ["oauth-config"],
    queryFn: api.oauthConfig,
    staleTime: 5 * 60_000,
  });
  if (!data?.google) return null;
  return (
    <div className="mt-4">
      {divider && (
        <div className="mb-4 flex items-center gap-3" aria-hidden="true">
          <span className="h-px flex-1 bg-border" />
          <span className="text-xs uppercase tracking-wide text-muted">
            {t("auth.oauth.or")}
          </span>
          <span className="h-px flex-1 bg-border" />
        </div>
      )}
      <a
        href="/api/auth/oauth/google/start"
        data-testid="btn-oauth-google"
        className="flex min-h-10 w-full items-center justify-center gap-2 rounded-sm border border-border bg-surface px-3 text-sm font-medium text-text transition-colors hover:bg-surface-hover"
      >
        <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden="true">
          <path
            fill="#4285F4"
            d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.5h6.4a5.5 5.5 0 0 1-2.4 3.6v3h3.9c2.3-2.1 3.6-5.2 3.6-8.8Z"
          />
          <path
            fill="#34A853"
            d="M12 24c3.2 0 5.9-1.1 7.9-2.9l-3.9-3a7.2 7.2 0 0 1-10.7-3.8H1.3v3.1A12 12 0 0 0 12 24Z"
          />
          <path fill="#FBBC05" d="M5.3 14.3a7.2 7.2 0 0 1 0-4.6V6.6H1.3a12 12 0 0 0 0 10.8l4-3.1Z" />
          <path
            fill="#EA4335"
            d="M12 4.8c1.8 0 3.4.6 4.6 1.8l3.4-3.4A12 12 0 0 0 1.3 6.6l4 3.1A7.2 7.2 0 0 1 12 4.8Z"
          />
        </svg>
        {t("auth.oauth.google")}
      </a>
    </div>
  );
}
