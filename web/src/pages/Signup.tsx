import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ApiError, api } from "../api/client";
import { useT } from "../i18n";
import { mapApiError } from "../lib/errors";
import AuthLayout from "../components/AuthLayout";
import Button from "../components/ui/Button";
import Input from "../components/ui/Input";

export default function Register() {
  const { t } = useT();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [acceptTos, setAcceptTos] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await api.register(email, password, true);
      // S5: register KHÔNG set cookie → tự login lấy session.
      const user = await api.login(email, password);
      queryClient.setQueryData(["me"], user);
      toast.success(t("auth.signup.created"));
      // Route theo is_verified: chưa verify → trang chủ "/" (route guard VerifyGating
      // mở modal verify); đã verify → /jobs như login.
      navigate(user.is_verified === false ? "/" : "/jobs");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : t("errors.generic"));
      toast.error(mapApiError(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthLayout
      title={t("auth.signup.title")}
      subtitle={t("auth.signup.subtitle")}
      footer={
        <>
          {t("auth.signup.haveAccount")}{" "}
          <Link
            to="/signin"
            className="inline-flex min-h-6 items-center text-accent-text hover:underline"
          >
            {t("nav.signIn")}
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <Input
          label="Email"
          testid="input-email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <Input
          label={t("auth.password")}
          testid="input-password"
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
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
            <Link
              to="/legal"
              className="inline-flex min-h-6 items-center text-accent-text hover:underline"
            >
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
    </AuthLayout>
  );
}
