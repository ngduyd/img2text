import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import { useT } from "../i18n";
import Button from "../components/ui/Button";
import Input from "../components/ui/Input";

export default function Reset() {
  const { t } = useT();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (password !== password2) {
      setError(t("auth.reset.mismatch"));
      return;
    }
    setLoading(true);
    try {
      await api.resetPassword(token, password);
      navigate("/signin");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : t("errors.generic"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main id="main" className="mx-auto max-w-sm p-6">
      <h1 className="mb-4 text-xl font-bold">{t("auth.reset.title")}</h1>
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <Input
          label={t("auth.reset.newPassword")}
          testid="input-password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder={t("auth.reset.newPassword")}
        />
        <Input
          label={t("auth.reset.repeatPassword")}
          testid="input-password2"
          type="password"
          value={password2}
          onChange={(e) => setPassword2(e.target.value)}
          placeholder={t("auth.reset.repeatPassword")}
        />
        {error && (
          <p data-testid="error-detail" className="text-sm text-error">
            {error}
          </p>
        )}
        <Button testid="btn-reset" type="submit" loading={loading}>
          {t("auth.reset.submit")}
        </Button>
      </form>
    </main>
  );
}
