import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ApiError, api } from "../api/client";
import { mapApiError } from "../lib/errors";
import { translate, useT } from "../i18n";
import type { RegionOut } from "../api/types";
import Button from "./ui/Button";

/** Task 2: inline per-region text edit — save → PATCH region + invalidate job query. */
export default function RegionEditor({
  jobId,
  region,
  onSaved,
  onCancel,
}: {
  jobId: string;
  region: RegionOut;
  onSaved: (rid: string, text: string, markdownReplaced: boolean) => void;
  onCancel: () => void;
}) {
  const { t } = useT();
  const [value, setValue] = useState(region.text);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const queryClient = useQueryClient();

  const save = async () => {
    if (saving) return;
    setSaving(true);
    setError(null);
    try {
      const res = await api.patchRegion(jobId, region.id, value);
      toast.success(translate("editor.saved"));
      onSaved(region.id, value, res.markdown_replaced);
      await queryClient.invalidateQueries({ queryKey: ["job", jobId] });
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : translate("editor.saveFailed"));
      toast.error(mapApiError(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mt-2">
      {error && (
        <p data-testid={`region-error-${region.id}`} className="mb-1 text-sm text-error">
          {error}
        </p>
      )}
      <textarea
        data-testid={`textarea-region-${region.id}`}
        aria-label={t("region.textAria", { id: region.id })}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        className="mb-2 w-full rounded-md border border-border bg-surface p-2 text-sm text-text"
      />
      <div className="flex gap-2">
        <Button
          testid={`btn-save-region-${region.id}`}
          size="sm"
          loading={saving}
          disabled={saving}
          onClick={save}
        >
          {t("common.save")}
        </Button>
        <Button
          testid={`btn-cancel-region-${region.id}`}
          size="sm"
          variant="secondary"
          onClick={onCancel}
        >
          {t("common.cancel")}
        </Button>
      </div>
    </div>
  );
}
