import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { ApiError, api } from "../api/client";
import { mapApiError } from "../lib/errors";
import OcrBadge from "../components/OcrBadge";
import LangSwitch from "../components/LangSwitch";
import Badge from "../components/ui/Badge";
import Button from "../components/ui/Button";
import Card from "../components/ui/Card";
import Input from "../components/ui/Input";
import PageHeader from "../components/PageHeader";
import PageShell from "../components/PageShell";
import Skeleton from "../components/ui/Skeleton";
import { useT } from "../i18n";

/** Profile for both roles (Task 3). PATCH /api/auth/profile via api.updateProfile. */
export default function Profile() {
  const { t } = useT();
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
      <PageShell width="form">
        <div data-testid="profile-loading" className="flex flex-col gap-4">
          <Skeleton className="h-8 w-40" />
          <div className="rounded-card border border-border bg-surface p-4 shadow-card">
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3" />
          </div>
          <div className="rounded-card border border-border bg-surface p-4 shadow-card">
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-10 w-full" />
          </div>
          <div className="rounded-card border border-border bg-surface p-4 shadow-card">
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-10 w-full" />
          </div>
        </div>
      </PageShell>
    );
  }

  async function savePassword(e: React.FormEvent) {
    e.preventDefault();
    setPwError(null);
    setPwSuccess(false);
    if (newPw !== newPw2) {
      setPwError(t("profile.pwMismatch")); // client-side check — no api call on mismatch
      return;
    }
    setPwBusy(true);
    try {
      await api.updateProfile({ current_password: curPw, new_password: newPw });
      toast.success(t("profile.saved"));
      setPwSuccess(true);
      setCurPw("");
      setNewPw("");
      setNewPw2("");
    } catch (err) {
      setPwError(err instanceof ApiError ? err.detail : t("profile.pwFailed"));
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
      toast.success(t("profile.saved"));
      queryClient.setQueryData(["me"], updated);
      setEmSuccess(true);
      setCurPw2("");
      setNewEmail("");
    } catch (err) {
      setEmError(err instanceof ApiError ? err.detail : t("profile.emailFailed"));
      toast.error(mapApiError(err));
    } finally {
      setEmBusy(false);
    }
  }

  return (
    <PageShell width="form">
      <PageHeader title={t("profile.title")} actions={<LangSwitch testid="lang-switch-settings" />} />
      <div className="flex flex-col gap-4">
        <Card title={t("profile.infoTitle")} testid="card-profile-info">
          <div className="flex flex-col gap-2 text-sm">
            <div className="flex items-center gap-2">
              <span className="text-muted">Email:</span>
              <span data-testid="profile-email">{me.email}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-muted">{t("profile.role")}</span>
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
              <span data-testid="profile-id" className="break-all font-mono">
                {me.id}
              </span>
            </div>
            {me.created_at && (
              <div className="flex items-center gap-2">
                <span className="text-muted">{t("profile.joined")}</span>
                <time dateTime={me.created_at} className="text-sm">
                  {new Date(me.created_at).toLocaleDateString(t("i18n.locale"))}
                </time>
              </div>
            )}
          </div>
        </Card>

        <Card title={t("profile.changePassword")} testid="card-password">
          <form onSubmit={savePassword} className="flex flex-col gap-3">
            <Input
              label={t("profile.currentPassword")}
              type="password"
              autoComplete="current-password"
              testid="input-current-password"
              value={curPw}
              onChange={(e) => setCurPw(e.target.value)}
            />
            <Input
              label={t("profile.newPassword")}
              type="password"
              autoComplete="new-password"
              testid="input-new-password"
              value={newPw}
              onChange={(e) => setNewPw(e.target.value)}
            />
            <Input
              label={t("profile.repeatPassword")}
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
                {t("profile.pwSuccess")}
              </p>
            )}
            <div>
              <Button type="submit" testid="btn-save-password" loading={pwBusy}>
                {t("profile.savePassword")}
              </Button>
            </div>
          </form>
        </Card>

        <Card title={t("profile.changeEmail")} testid="card-email">
          <form onSubmit={saveEmail} className="flex flex-col gap-3">
            <Input
              label={t("profile.currentPassword")}
              type="password"
              autoComplete="current-password"
              testid="input-current-password-2"
              value={curPw2}
              onChange={(e) => setCurPw2(e.target.value)}
            />
            <Input
              label={t("profile.newEmail")}
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
                {t("profile.emailSuccess")}
              </p>
            )}
            <div>
              <Button type="submit" testid="btn-save-email" loading={emBusy}>
                {t("profile.saveEmail")}
              </Button>
            </div>
          </form>
        </Card>
      </div>
    </PageShell>
  );
}
