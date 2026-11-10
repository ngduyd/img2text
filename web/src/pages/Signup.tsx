import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ApiError, api } from "../api/client";
import { useT } from "../i18n";
import { mapApiError } from "../lib/errors";
import AuthIntro from "../components/AuthIntro";
import AuthLayout from "../components/AuthLayout";
import OAuthButtons from "../components/OAuthButtons";
import Button from "../components/ui/Button";
import Input from "../components/ui/Input";

const PASSWORD_MIN = 8;

/** Login ngay sau register: chịu middleware 1s/request của /api/auth/* → thử
 *  lại 1 lần sau 1,2s khi gặp 429 rate_limited. Các 429 khác trả nguyên. */
async function loginAfterRegister(email: string, password: string) {
  try {
    return await api.login(email, password);
  } catch (err) {
    if (err instanceof ApiError && err.status === 429 && err.code === "rate_limited") {
      await new Promise((r) => setTimeout(r, 1200));
      return await api.login(email, password);
    }
    throw err;
  }
}

export default function Register() {
  const { t } = useT();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [acceptTos, setAcceptTos] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  /** Bước 2: chỉ dùng khi server bật xác thực email (có SMTP). */
  const [step, setStep] = useState<"form" | "verify">("form");
  const [code, setCode] = useState("");
  /** Đồng hồ gửi lại mã: mở bước 2 là bắt đầu 60s, hết mới bấm được. */
  const [cooldown, setCooldown] = useState(0);
  const [verifying, setVerifying] = useState(false);
  const [resending, setResending] = useState(false);

  const passwordTooShort = password.length > 0 && password.length < PASSWORD_MIN;

  useEffect(() => {
    if (step !== "verify" || cooldown <= 0) return;
    const id = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(id);
  }, [step, cooldown]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (passwordTooShort) return;
    setError(null);
    setLoading(true);
    let registered = false;
    try {
      await api.register(email, password, true);
      registered = true;
      // S5: register KHÔNG set cookie → tự login lấy session. Server có
      // middleware 1 giây/lần cho mỗi (IP + User-Agent) trên các route auth →
      // login ngay sau register bị 429 {code:"rate_limited"}. Chờ 1,2s rồi thử
      // lại MỘT lần thay vì báo lỗi cho người dùng vừa đăng ký xong.
      const user = await loginAfterRegister(email, password);
      queryClient.setQueryData(["me"], user);
      if (user.is_verified === false) {
        // Có SMTP: sang bước nhập mã ngay tại đây (thay vì đẩy về "/" rồi mở
        // modal — user không hiểu vì sao bị chặn sau khi vừa đăng ký xong).
        setStep("verify");
        setCooldown(60);
        toast.success(t("auth.signup.created"));
        return;
      }
      toast.success(t("auth.signup.created"));
      navigate("/jobs");
    } catch (err) {
      // 429 có thể rơi vào bước login NGAY SAU register: tài khoản + email xác
      // thực đã được tạo rồi, nên đừng để người dùng tưởng đăng ký thất bại
      // (họ vẫn nhận được email — trước đây gây hiểu là "429 mà vẫn gửi mail").
      if (registered && err instanceof ApiError && err.status === 429) {
        // 429 ở bước login NGAY SAU register: tài khoản + email đã tạo thật.
        toast.error(t("auth.signup.rateLimited"));
        navigate("/signin");
        return;
      }
      setError(err instanceof ApiError ? err.detail : t("errors.generic"));
      toast.error(mapApiError(err));
    } finally {
      setLoading(false);
    }
  }

  async function onVerify(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setVerifying(true);
    try {
      await api.verifyCode(code.trim());
      // setQueryData trước invalidate: VerifyGate đọc cache ["me"], nếu chỉ
      // invalidate thì trong lúc refetch nó vẫn thấy is_verified=false → bật lại
      // modal mã xác nhận ngay sau khi vừa xác nhận xong.
      queryClient.setQueryData(["me"], (u?: { is_verified?: boolean }) =>
        u ? { ...u, is_verified: true } : u,
      );
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      toast.success(t("auth.verify.success"));
      navigate("/jobs");
    } catch (err) {
      setError(
        err instanceof ApiError && err.detail === "invalid or expired code"
          ? t("auth.signup.verifyInvalid")
          : mapApiError(err),
      );
    } finally {
      setVerifying(false);
    }
  }

  async function onResend() {
    setResending(true);
    try {
      await api.verifyResend();
      setCooldown(60);
      toast.success(t("auth.signup.verifySent"));
    } catch (err) {
      toast.error(mapApiError(err));
    } finally {
      setResending(false);
    }
  }

  const footer = (
    <>
      {t("auth.signup.haveAccount")}{" "}
      <Link to="/signin" className="inline-flex min-h-6 items-center text-accent-text hover:underline">
        {t("nav.signIn")}
      </Link>
    </>
  );

  if (step === "verify") {
    return (
      <AuthLayout
        title={t("auth.signup.verifyTitle")}
        subtitle={t("auth.signup.verifySubtitle", { email })}
        footer={null}
        aside={<AuthIntro />}
      >
        <form onSubmit={onVerify} className="flex flex-col gap-4">
          {/* Ô mã cỡ lớn, căn giữa, giãn chữ: 6 số đọc như một khối thay vì
              dòng text bình thường (dễ đếm, dễ soát khi gõ sai). */}
          <div className="flex flex-col gap-1">
            <label htmlFor="input-verify-code" className="text-sm text-muted">
              {t("auth.verify.codeLabel")}
            </label>
            <input
              id="input-verify-code"
              data-testid="input-verify-code"
              inputMode="numeric"
              autoComplete="one-time-code"
              autoFocus
              maxLength={6}
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
              aria-describedby="verify-help"
              className="h-14 w-full rounded-sm border border-border bg-surface text-center font-mono text-2xl tracking-[0.5em] text-text tabular-nums"
            />
            <p id="verify-help" className="text-xs text-muted">
              {t("auth.signup.verifyHelp")}
            </p>
          </div>
          {error && (
            <p data-testid="error-detail" role="alert" className="text-sm text-error">
              {error}
            </p>
          )}
          <Button
            testid="btn-verify"
            type="submit"
            loading={verifying}
            disabled={code.length !== 6}
            className="w-full"
          >
            {t("auth.signup.verifySubmit")}
          </Button>
          <div className="flex items-center justify-between gap-2">
            <Button
              testid="btn-resend"
              type="button"
              variant="ghost"
              size="sm"
              loading={resending}
              disabled={cooldown > 0}
              onClick={onResend}
            >
              {cooldown > 0
                ? t("auth.signup.verifyResendIn", { s: cooldown })
                : t("auth.signup.verifyResend")}
            </Button>
            <button
              type="button"
              data-testid="btn-change-email"
              onClick={() => {
                setStep("form");
                setCode("");
                setError(null);
                setCooldown(0);
              }}
              className="inline-flex min-h-6 items-center text-sm text-accent-text hover:underline"
            >
              {t("auth.signup.changeEmail")}
            </button>
          </div>
        </form>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title={t("auth.signup.title")}
      subtitle={t("auth.signup.subtitle")}
      footer={footer}
      aside={<AuthIntro />}
    >
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <Input
          label={t("auth.email")}
          testid="input-email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <div className="flex flex-col gap-1">
          <label htmlFor="input-password" className="text-sm text-muted">
            {t("auth.password")}
          </label>
          <div className="relative">
            <input
              id="input-password"
              data-testid="input-password"
              type={showPassword ? "text" : "password"}
              autoComplete="new-password"
              required
              minLength={PASSWORD_MIN}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              aria-describedby="password-hint"
              aria-invalid={passwordTooShort || undefined}
              className={`h-10 w-full rounded-sm border bg-surface px-3 pr-16 text-text placeholder:text-muted ${
                passwordTooShort ? "border-error" : "border-border"
              }`}
            />
            <button
              type="button"
              onClick={() => setShowPassword((s) => !s)}
              className="absolute right-2 top-1/2 inline-flex min-h-6 -translate-y-1/2 items-center px-1 text-xs text-muted hover:text-text"
            >
              {showPassword ? t("auth.hide") : t("auth.show")}
            </button>
          </div>
          <p
            id="password-hint"
            data-testid="password-hint"
            className={`text-xs ${passwordTooShort ? "text-error" : "text-muted"}`}
          >
            {passwordTooShort ? t("auth.signup.passwordTooShort") : t("auth.signup.passwordHint")}
          </p>
        </div>
        {/* Spec 2026-11-04 (A2): bắt buộc đồng ý ToS — nút register khoá tới khi tick. */}
        <label className="inline-flex min-h-6 cursor-pointer items-start gap-2 text-sm text-muted">
          <input
            type="checkbox"
            data-testid="input-tos"
            checked={acceptTos}
            onChange={(e) => setAcceptTos(e.target.checked)}
            className="mt-0.5 h-6 min-h-6 w-6 min-w-6 shrink-0 accent-accent"
          />
          <span>
            {t("auth.signup.tosPrefix")}{" "}
            <Link to="/legal" className="inline-flex min-h-6 items-center text-accent-text hover:underline">
              {t("auth.signup.tosLink")}
            </Link>
          </span>
        </label>
        {error && (
          <p data-testid="error-detail" role="alert" className="text-sm text-error">
            {error}
          </p>
        )}
        <Button
          testid="btn-register"
          type="submit"
          loading={loading}
          disabled={!acceptTos}
          className="w-full"
        >
          {t("nav.signUp")}
        </Button>
      </form>
      <OAuthButtons />
    </AuthLayout>
  );
}
