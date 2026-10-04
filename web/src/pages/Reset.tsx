import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, api } from "../api/client";

export default function Reset() {
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
      setError("Mật khẩu nhập lại không khớp.");
      return;
    }
    setLoading(true);
    try {
      await api.resetPassword(token, password);
      navigate("/login");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Đã xảy ra lỗi.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-sm p-6">
      <h1 className="mb-4 text-xl font-bold">Đặt lại mật khẩu</h1>
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <input
          data-testid="input-password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Mật khẩu mới"
          className="rounded border border-gray-300 px-3 py-2"
        />
        <input
          data-testid="input-password2"
          type="password"
          value={password2}
          onChange={(e) => setPassword2(e.target.value)}
          placeholder="Nhập lại mật khẩu"
          className="rounded border border-gray-300 px-3 py-2"
        />
        {error && (
          <p data-testid="error-detail" className="text-sm text-red-600">
            {error}
          </p>
        )}
        <button
          data-testid="btn-reset"
          type="submit"
          disabled={loading}
          className="rounded bg-blue-600 px-3 py-2 font-semibold text-white disabled:opacity-50"
        >
          Đặt lại mật khẩu
        </button>
      </form>
    </main>
  );
}
