import { useState, type FormEvent } from "react";
import { ApiError, api } from "../api/client";

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
    <main className="mx-auto max-w-sm p-6">
      <h1 className="mb-4 text-xl font-bold">Quên mật khẩu</h1>
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="Email"
          className="rounded border border-gray-300 px-3 py-2"
        />
        {error && (
          <p data-testid="error-detail" className="text-sm text-red-600">
            {error}
          </p>
        )}
        {/* Constant message on 202 regardless of email existence (anti-enumeration). */}
        {sent && (
          <p data-testid="forgot-success" className="text-sm text-green-700">
            Kiểm tra email của bạn.
          </p>
        )}
        <button
          data-testid="btn-forgot"
          type="submit"
          disabled={loading}
          className="rounded bg-blue-600 px-3 py-2 font-semibold text-white disabled:opacity-50"
        >
          Gửi email đặt lại
        </button>
      </form>
    </main>
  );
}
