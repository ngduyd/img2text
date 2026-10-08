import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { ApiError, api } from "../api/client";
import { mapApiError } from "../lib/errors";
import AuthLayout from "../components/AuthLayout";
import Button from "../components/ui/Button";
import Input from "../components/ui/Input";

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
      toast.success("Account created. Please sign in.");
      navigate("/signin");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "An error occurred.");
      toast.error(mapApiError(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthLayout
      title="Sign up"
      subtitle="Create an account to get started."
      footer={
        <>
          Already have an account?{" "}
          <Link to="/signin" className="text-accent-text hover:underline">
            Sign in
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
        <Input
          label="Password"
          testid="input-password"
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error && (
          <p data-testid="error-detail" role="alert" className="text-sm text-error">
            {error}
          </p>
        )}
        <Button testid="btn-register" type="submit" loading={loading} className="w-full">
          Sign up
        </Button>
      </form>
    </AuthLayout>
  );
}
