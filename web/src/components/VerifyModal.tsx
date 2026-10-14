import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api/client";
import { useT } from "../i18n";
import { mapApiError } from "../lib/errors";
import Button from "./ui/Button";
import Input from "./ui/Input";

/** S5: TTL 5 phút — server không trả expiry nên client đếm local từ lúc mở modal. */
const TTL_SECONDS = 300;
/** Client-side cooldown giữa 2 lần resend (server chỉ limit theo email/24h).
 *  Khởi đầu 0: gating mở modal → user chưa bấm resend → resend bật ngay. */
const RESEND_COOLDOWN = 30;

function mmss(total: number): string {
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** Server detail/code → i18n: 422 detail cứng "invalid or expired code",
 *  429 {code:"email_limit"} (handler main.py). */
function verifyError(err: unknown, t: (key: string) => string): string {
  if (err instanceof ApiError) {
    if (err.code === "email_limit") return t("errors.email_limit");
    if (err.detail === "invalid or expired code") return t("auth.verify.invalid");
  }
  return mapApiError(err);
}

interface VerifyModalProps {
  email?: string;
  /** Xác thực thành công (hoặc đã verified) → refetch ["me"] + unlock app. */
  onVerified?: () => void;
  /** Logout từ modal → gọi API logout; điều hướng do <Link> lo. */
  onLogout?: () => void;
}

/** R51: overlay toàn màn hình, KHÔNG dismiss — che nội dung thay vì ẩn nó
 *  (nav vẫn render phía dưới). Input 6 số + countdown TTL + resend cooldown. */
export default function VerifyModal({ email, onVerified, onLogout }: VerifyModalProps) {
  const { t } = useT();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [ttl, setTtl] = useState(TTL_SECONDS);
  const [cooldown, setCooldown] = useState(0);
  const [resending, setResending] = useState(false);

  useEffect(() => {
    const id = window.setInterval(() => {
      setTtl((s) => (s > 0 ? s - 1 : 0));
      setCooldown((s) => (s > 0 ? s - 1 : 0));
    }, 1000);
    return () => window.clearInterval(id);
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await api.verifyCode(code);
      await onVerified?.();
    } catch (err) {
      // 400 already_verified (code hoặc detail) → user đã verify (tab khác),
      // refetch ["me"] + đóng modal thay vì kẹt submit code stale.
      if (
        err instanceof ApiError &&
        (err.code === "already_verified" || err.detail === "already_verified")
      ) {
        await onVerified?.();
        return;
      }
      setError(verifyError(err, t));
    } finally {
      setLoading(false);
    }
  }

  async function onResend() {
    setError(null);
    setResending(true);
    try {
      await api.verifyResend();
      // Code mới ghi đè code cũ → reset TTL + cooldown.
      setTtl(TTL_SECONDS);
      setCooldown(RESEND_COOLDOWN);
      setCode("");
    } catch (err) {
      // 400 {code:"already_verified"} → coi như verified, unlock
      // (align onSubmit: check code hoặc detail).
      if (
        err instanceof ApiError &&
        (err.code === "already_verified" || err.detail === "already_verified")
      ) {
        await onVerified?.();
        return;
      }
      setError(verifyError(err, t));
    } finally {
      setResending(false);
    }
  }

  return (
    <div
      data-testid="verify-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="verify-title"
      className="fixed inset-0 z-50 flex min-h-dvh items-center justify-center bg-bg p-4"
    >
      <div className="w-full max-w-sm rounded-card border border-border bg-surface p-6 shadow-card">
        <h1 id="verify-title" className="text-xl font-bold text-text">
          {t("auth.verify.title")}
        </h1>
        <p className="mt-1 text-sm text-muted">
          {email
            ? t("auth.verify.subtitleWithEmail", { email })
            : t("auth.verify.subtitle")}
        </p>
        <form onSubmit={onSubmit} className="mt-4 flex flex-col gap-3">
          <Input
            label={t("auth.verify.codeLabel")}
            testid="input-code"
            autoFocus
            inputMode="numeric"
            maxLength={6}
            autoComplete="one-time-code"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
          />
          <p data-testid="verify-ttl" className="text-xs text-muted">
            {ttl > 0
              ? t("auth.verify.expiresIn", { time: mmss(ttl) })
              : t("auth.verify.expired")}
          </p>
          {error && (
            <p data-testid="error-detail" role="alert" className="text-sm text-error">
              {error}
            </p>
          )}
          <Button
            testid="btn-verify"
            type="submit"
            loading={loading}
            disabled={code.length !== 6}
            className="w-full"
          >
            {t("auth.verify.submit")}
          </Button>
          <Button
            testid="btn-resend"
            type="button"
            variant="secondary"
            disabled={cooldown > 0 || resending}
            onClick={onResend}
            className="w-full"
          >
            {cooldown > 0
              ? t("auth.verify.resendIn", { s: cooldown })
              : t("auth.verify.resend")}
          </Button>
          <Link
            to="/signin"
            data-testid="verify-logout"
            onClick={onLogout}
            className="text-center text-sm text-muted hover:text-text hover:underline"
          >
            {t("auth.verify.logout")}
          </Link>
        </form>
      </div>
    </div>
  );
}
