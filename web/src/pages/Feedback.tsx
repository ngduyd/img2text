import { useState } from "react";
import { toast } from "sonner";
import { api } from "../api/client";
import { mapApiError } from "../lib/errors";
import Button from "../components/ui/Button";
import Card from "../components/ui/Card";
import PageHeader from "../components/PageHeader";
import PageShell from "../components/PageShell";
import Textarea from "../components/ui/Textarea";
import { useT } from "../i18n";

const MAX = 2000;

/** Lane B2 (wave-5 S6): trang /feedback — textarea + char count + submit → toast R59. */
export default function Feedback() {
  const { t } = useT();
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);

  const over = content.length > MAX;
  const disabled = content.trim().length === 0 || over;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (disabled) return;
    setBusy(true);
    try {
      await api.submitFeedback(content, window.location.pathname);
      toast.success(t("feedback.success"));
      setContent("");
    } catch (err) {
      toast.error(mapApiError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <PageShell>
      <PageHeader title={t("feedback.title")} />
      <Card testid="card-feedback">
        <form onSubmit={submit} className="flex flex-col gap-3">
          <Textarea
            label={t("feedback.label")}
            testid="feedback-content"
            id="feedback-content"
            rows={6}
            value={content}
            maxLength={MAX + 1}
            placeholder={t("feedback.placeholder")}
            onChange={(e) => setContent(e.target.value)}
          />
          <span
            data-testid="feedback-count"
            className={`text-xs ${over ? "text-error" : "text-muted"}`}
          >
            {t("feedback.count", { n: content.length, max: MAX })}
          </span>
          <div>
            <Button type="submit" testid="feedback-submit" loading={busy} disabled={disabled}>
              {t("feedback.submit")}
            </Button>
          </div>
        </form>
      </Card>
    </PageShell>
  );
}
