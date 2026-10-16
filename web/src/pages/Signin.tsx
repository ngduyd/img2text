import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ApiError, api } from "../api/client";
import { useT } from "../i18n";
import { mapApiError } from "../lib/errors";
import AuthLayout from "../components/AuthLayout";
import Button from "../components/ui/Button";
import Input from "../components/ui/Input";

export default function Login() {
  const { t } = useT();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await api.login(email, password);
      toast.success(t("auth.signin.signedIn"));
      navigate("/jobs");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : t("errors.generic"));
      toast.error(mapApiError(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthLayout
      title={t("auth.signin.title")}
      subtitle={t("auth.signin.subtitle")}
      footer={
        <>
          {t("auth.signin.noAccount")}{" "}
          <Link to="/signup" className="text-accent-text hover:underline">
            {t("nav.signUp")}
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
        <div className="flex flex-col gap-1">
          <div className="flex items-center justify-between">
            <label htmlFor="input-password" className="text-sm text-muted">
              {t("auth.password")}
            </label>
            <Link to="/forgot" className="text-xs text-accent-text hover:underline">
              {t("auth.signin.forgot")}
            </Link>
          </div>
          <div className="relative">
            <input
              id="input-password"
              data-testid="input-password"
              type={showPassword ? "text" : "password"}
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="h-10 w-full rounded-sm border border-border bg-surface px-3 pr-16 text-text placeholder:text-muted"
            />
            <button
              type="button"
              onClick={() => setShowPassword((s) => !s)}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-muted hover:text-text"
            >
              {showPassword ? t("auth.hide") : t("auth.show")}
            </button>
          </div>
        </div>
        {error && (
          <p data-testid="error-detail" role="alert" className="text-sm text-error">
            {error}
          </p>
        )}
        <Button testid="btn-login" type="submit" loading={loading} className="w-full">
          {t("nav.signIn")}
        </Button>
      </form>
    </AuthLayout>
  );
}
