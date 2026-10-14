import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import { useT } from "../i18n";
import { mapApiError } from "../lib/errors";
import Button from "../components/ui/Button";
import Input from "../components/ui/Input";

/** S5: reset contract {email, code, password} — mã 6 số lấy từ email (TTL 5p);
 *  không còn ?token= (server đã drop token flow). Email prefill từ query. */
export default function Reset() {
  const { t } = useT();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [email, setEmail] = useState(params.get("email") ?? "");
  const [code, setCode] = useState("");
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
      await api.resetPassword({ email, code, password });
      navigate("/signin");
    } catch (err) {
      // 422 detail cứng của cả forgot flow lẫn reset → map i18n (auth.verify.*).
      setError(
        err instanceof ApiError && err.detail === "invalid or expired code"
          ? t("auth.verify.invalid")
          : mapApiError(err),
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <main id="main" className="mx-auto max-w-sm p-6">
      <h1 className="mb-4 text-xl font-bold">{t("auth.reset.title")}</h1>
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <Input
          label={t("auth.reset.email")}
          testid="input-email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="Email"
        />
        <Input
          label={t("auth.reset.code")}
          testid="input-code"
          inputMode="numeric"
          maxLength={6}
          autoComplete="one-time-code"
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
          placeholder="000000"
        />
        <Input
          label={t("auth.reset.newPassword")}
          testid="input-password"
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder={t("auth.reset.newPassword")}
        />
        <Input
          label={t("auth.reset.repeatPassword")}
          testid="input-password2"
          type="password"
          autoComplete="new-password"
          value={password2}
          onChange={(e) => setPassword2(e.target.value)}
          placeholder={t("auth.reset.repeatPassword")}
        />
        {error && (
          <p data-testid="error-detail" role="alert" className="text-sm text-error">
            {error}
          </p>
        )}
        <Button
          testid="btn-reset"
          type="submit"
          loading={loading}
          disabled={code.length !== 6}
        >
          {t("auth.reset.submit")}
        </Button>
      </form>
    </main>
  );
}
