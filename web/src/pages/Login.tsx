import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ApiError, api } from "../api/client";
import { mapApiError } from "../lib/errors";
import Button from "../components/ui/Button";
import Card from "../components/ui/Card";
import Input from "../components/ui/Input";

export default function Login() {
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
      await api.login(email, password);
      toast.success("Đã đăng nhập.");
      navigate("/jobs");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Đã xảy ra lỗi.");
      toast.error(mapApiError(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main id="main" className="mx-auto max-w-sm p-4 sm:p-6">
      <h1 className="mb-6 text-2xl font-bold tracking-tight">Đăng nhập</h1>
      <Card>
        <form onSubmit={onSubmit} className="flex flex-col gap-4">
          <Input
            label="Email"
            testid="input-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <Input
            label="Mật khẩu"
            testid="input-password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {error && (
            <p data-testid="error-detail" role="alert" className="text-sm text-error">
              {error}
            </p>
          )}
          <Button testid="btn-login" type="submit" loading={loading} className="w-full">
            Đăng nhập
          </Button>
        </form>
      </Card>
    </main>
  );
}
