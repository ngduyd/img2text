import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import Button from "../components/ui/Button";
import Input from "../components/ui/Input";

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
    <main id="main" className="mx-auto max-w-sm p-6">
      <h1 className="mb-4 text-xl font-bold">Đặt lại mật khẩu</h1>
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <Input
          label="Mật khẩu mới"
          testid="input-password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Mật khẩu mới"
        />
        <Input
          label="Nhập lại mật khẩu"
          testid="input-password2"
          type="password"
          value={password2}
          onChange={(e) => setPassword2(e.target.value)}
          placeholder="Nhập lại mật khẩu"
        />
        {error && (
          <p data-testid="error-detail" className="text-sm text-error">
            {error}
          </p>
        )}
        <Button testid="btn-reset" type="submit" loading={loading}>
          Đặt lại mật khẩu
        </Button>
      </form>
    </main>
  );
}
