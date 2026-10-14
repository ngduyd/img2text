import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../api/client";
import { useT } from "../i18n";
import Button from "../components/ui/Button";
import Input from "../components/ui/Input";

export default function Forgot() {
  const { t } = useT();
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await api.forgotEmail(email);
      setSent(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : t("errors.generic"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main id="main" className="mx-auto max-w-sm p-6">
      <h1 className="mb-4 text-xl font-bold">{t("auth.forgot.title")}</h1>
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <Input
          label="Email"
          testid="input-email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="Email"
        />
        {error && (
          <p data-testid="error-detail" className="text-sm text-error">
            {error}
          </p>
        )}
        {/* Constant message on 200 regardless of email existence (anti-enumeration). */}
        {sent && (
          <p data-testid="forgot-success" className="text-sm text-success">
            {t("auth.forgot.sent")}
          </p>
        )}
        {/* S5: code 6 số → form reset {email, code, password} (không còn token link). */}
        {sent && (
          <Link
            to={`/reset?email=${encodeURIComponent(email)}`}
            data-testid="link-reset"
            className="text-sm text-accent-text hover:underline"
          >
            {t("auth.forgot.enterCode")}
          </Link>
        )}
        <Button testid="btn-forgot" type="submit" loading={loading}>
          {t("auth.forgot.submit")}
        </Button>
      </form>
    </main>
  );
}
