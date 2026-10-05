import { useState, type FormEvent } from "react";
import { ApiError, api } from "../api/client";
import Button from "../components/ui/Button";
import Input from "../components/ui/Input";

export default function Forgot() {
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
      setError(err instanceof ApiError ? err.detail : "Đã xảy ra lỗi.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main id="main" className="mx-auto max-w-sm p-6">
      <h1 className="mb-4 text-xl font-bold">Quên mật khẩu</h1>
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
            Kiểm tra email của bạn.
          </p>
        )}
        <Button testid="btn-forgot" type="submit" loading={loading}>
          Gửi email đặt lại
        </Button>
      </form>
    </main>
  );
}
