import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, api } from "../api/client";

export default function Register() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await api.register(email, password);
      navigate("/login");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Đã xảy ra lỗi.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-sm p-6">
      <h1 className="mb-4 text-xl font-bold">Đăng ký</h1>
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="Email"
          className="rounded border border-gray-300 px-3 py-2"
        />
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Mật khẩu"
          className="rounded border border-gray-300 px-3 py-2"
        />
        {error && (
          <p data-testid="error-detail" className="text-sm text-red-600">
            {error}
          </p>
        )}
        <button
          data-testid="btn-register"
          type="submit"
          disabled={loading}
          className="rounded bg-blue-600 px-3 py-2 font-semibold text-white disabled:opacity-50"
        >
          Đăng ký
        </button>
      </form>
    </main>
  );
}
