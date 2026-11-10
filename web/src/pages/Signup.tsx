import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { FileText, Languages, ShieldCheck } from "lucide-react";
import { ApiError, api } from "../api/client";
import { useT } from "../i18n";
import { mapApiError } from "../lib/errors";
import AuthLayout from "../components/AuthLayout";
import OAuthButtons from "../components/OAuthButtons";
import Button from "../components/ui/Button";
import Input from "../components/ui/Input";

const PASSWORD_MIN = 8;

/** Panel giới thiệu: chỉ hiện ≥lg, để form vẫn là trung tâm ở màn hẹp. */
function SignupAside() {
  const { t } = useT();
  const points = [
    { icon: FileText, text: t("auth.signup.aside1") },
    { icon: Languages, text: t("auth.signup.aside2") },
    { icon: ShieldCheck, text: t("auth.signup.aside3") },
  ];
  return (
    <div className="rounded-card border border-border bg-surface p-8">
      <p className="text-xs font-medium uppercase tracking-wider text-accent-text">
        img2text
      </p>
      <h2 className="mt-3 text-2xl font-bold leading-tight text-text">
        {t("auth.signup.asideTitle")}
      </h2>
      <ul className="mt-6 flex flex-col gap-4">
        {points.map(({ icon: Icon, text }) => (
          <li key={text} className="flex gap-3 text-sm text-muted">
            <Icon className="mt-0.5 h-4 w-4 shrink-0 text-accent-text" aria-hidden="true" />
            <span className="leading-relaxed">{text}</span>
          </li>
        ))}
      </ul>
    </div>
  );
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
  const [verifying, setVerifying] = useState(false);
  const [resending, setResending] = useState(false);

  const passwordTooShort = password.length > 0 && password.length < PASSWORD_MIN;

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (passwordTooShort) return;
    setError(null);
    setLoading(true);
    try {
      await api.register(email, password, true);
      // S5: register KHÔNG set cookie → tự login lấy session.
      const user = await api.login(email, password);
      queryClient.setQueryData(["me"], user);
      if (user.is_verified === false) {
        // Có SMTP: sang bước nhập mã ngay tại đây (thay vì đẩy về "/" rồi mở
        // modal — user không hiểu vì sao bị chặn sau khi vừa đăng ký xong).
        setStep("verify");
        toast.success(t("auth.signup.created"));
        return;
      }
      toast.success(t("auth.signup.created"));
      navigate("/jobs");
    } catch (err) {
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
        footer={footer}
      >
        <form onSubmit={onVerify} className="flex flex-col gap-4">
          <Input
            label={t("auth.verify.codeLabel")}
            testid="input-verify-code"
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
          />
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
          <Button
            testid="btn-resend"
            type="button"
            variant="ghost"
            size="sm"
            loading={resending}
            onClick={onResend}
            className="w-full"
          >
            {t("auth.signup.verifyResend")}
          </Button>
        </form>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title={t("auth.signup.title")}
      subtitle={t("auth.signup.subtitle")}
      footer={footer}
      aside={<SignupAside />}
    >
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <Input
          label="Email"
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
              className="h-10 w-full rounded-sm border border-border bg-surface px-3 pr-16 text-text placeholder:text-muted"
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
            {t("auth.signup.passwordHint")}
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
