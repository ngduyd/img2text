import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { ApiError, api } from "../api/client";
import { mapApiError } from "../lib/errors";
import OcrBadge from "../components/OcrBadge";
import Badge from "../components/ui/Badge";
import Button from "../components/ui/Button";
import Card from "../components/ui/Card";
import Input from "../components/ui/Input";

/** Profile for both roles (Task 3). PATCH /api/auth/profile via api.updateProfile. */
export default function Profile() {
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me });
  const queryClient = useQueryClient();

  const [curPw, setCurPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [newPw2, setNewPw2] = useState("");
  const [pwError, setPwError] = useState<string | null>(null);
  const [pwBusy, setPwBusy] = useState(false);
  const [pwSuccess, setPwSuccess] = useState(false);

  const [curPw2, setCurPw2] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [emError, setEmError] = useState<string | null>(null);
  const [emBusy, setEmBusy] = useState(false);
  const [emSuccess, setEmSuccess] = useState(false);

  if (!me) {
    // Loading state instead of blank page while [me] resolves (ui-ux-dev checklist).
    return (
      <main id="main" className="mx-auto max-w-3xl p-4">
        <p data-testid="profile-loading" className="text-sm text-muted">
          Đang tải hồ sơ…
        </p>
      </main>
    );
  }

  async function savePassword(e: React.FormEvent) {
    e.preventDefault();
    setPwError(null);
    setPwSuccess(false);
    if (newPw !== newPw2) {
      setPwError("Mật khẩu xác nhận không khớp."); // client-side check — no api call on mismatch
      return;
    }
    setPwBusy(true);
    try {
      await api.updateProfile({ current_password: curPw, new_password: newPw });
      toast.success("Đã lưu thay đổi.");
      setPwSuccess(true);
      setCurPw("");
      setNewPw("");
      setNewPw2("");
    } catch (err) {
      setPwError(err instanceof ApiError ? err.detail : "Đổi mật khẩu thất bại.");
      toast.error(mapApiError(err));
    } finally {
      setPwBusy(false);
    }
  }

  async function saveEmail(e: React.FormEvent) {
    e.preventDefault();
    setEmError(null);
    setEmSuccess(false);
    setEmBusy(true);
    try {
      const updated = await api.updateProfile({ current_password: curPw2, email: newEmail });
      toast.success("Đã lưu thay đổi.");
      queryClient.setQueryData(["me"], updated);
      setEmSuccess(true);
      setCurPw2("");
      setNewEmail("");
    } catch (err) {
      setEmError(err instanceof ApiError ? err.detail : "Đổi email thất bại.");
      toast.error(mapApiError(err));
    } finally {
      setEmBusy(false);
    }
  }

  return (
    <main id="main" className="mx-auto max-w-3xl p-4">
      <h1 className="mb-4 text-xl font-bold">Hồ sơ</h1>
      <div className="flex flex-col gap-4">
        <Card title="Thông tin" testid="card-profile-info">
          <div className="flex flex-col gap-2 text-sm">
            <div className="flex items-center gap-2">
              <span className="text-muted">Email:</span>
              <span data-testid="profile-email">{me.email}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-muted">Vai trò:</span>
              <Badge testid="profile-role" tone={me.role === "admin" ? "info" : "neutral"}>
                {me.role === "admin" ? "Admin" : "User"}
              </Badge>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-muted">OCR:</span>
              <OcrBadge enabled={me.ocr_enabled} testid="badge-ocr-profile" />
            </div>
            <div className="flex items-center gap-2">
              <span className="text-muted">ID:</span>
              <span data-testid="profile-id" className="break-all">
                {me.id}
              </span>
            </div>
            <p className="text-muted">Ngày tham gia: cập nhật sau</p>
          </div>
        </Card>

        <Card title="Đổi mật khẩu" testid="card-password">
          <form onSubmit={savePassword} className="flex flex-col gap-3">
            <Input
              label="Mật khẩu hiện tại"
              type="password"
              autoComplete="current-password"
              testid="input-current-password"
              value={curPw}
              onChange={(e) => setCurPw(e.target.value)}
            />
            <Input
              label="Mật khẩu mới"
              type="password"
              autoComplete="new-password"
              testid="input-new-password"
              value={newPw}
              onChange={(e) => setNewPw(e.target.value)}
            />
            <Input
              label="Nhập lại mật khẩu mới"
              type="password"
              autoComplete="new-password"
              testid="input-new-password2"
              value={newPw2}
              onChange={(e) => setNewPw2(e.target.value)}
            />
            {pwError && (
              <p data-testid="password-error" role="alert" className="text-sm text-error">
                {pwError}
              </p>
            )}
            {pwSuccess && (
              <p data-testid="password-success" className="text-sm text-success">
                Đổi mật khẩu thành công. Phiên đăng nhập khác đã bị đăng xuất.
              </p>
            )}
            <div>
              <Button type="submit" testid="btn-save-password" loading={pwBusy}>
                Lưu mật khẩu
              </Button>
            </div>
          </form>
        </Card>

        <Card title="Đổi email" testid="card-email">
          <form onSubmit={saveEmail} className="flex flex-col gap-3">
            <Input
              label="Mật khẩu hiện tại"
              type="password"
              autoComplete="current-password"
              testid="input-current-password-2"
              value={curPw2}
              onChange={(e) => setCurPw2(e.target.value)}
            />
            <Input
              label="Email mới"
              type="email"
              autoComplete="email"
              testid="input-new-email"
              value={newEmail}
              onChange={(e) => setNewEmail(e.target.value)}
            />
            {emError && (
              <p data-testid="email-error" role="alert" className="text-sm text-error">
                {emError}
              </p>
            )}
            {emSuccess && (
              <p data-testid="email-success" className="text-sm text-success">
                Đổi email thành công.
              </p>
            )}
            <div>
              <Button type="submit" testid="btn-save-email" loading={emBusy}>
                Lưu email
              </Button>
            </div>
          </form>
        </Card>
      </div>
    </main>
  );
}
