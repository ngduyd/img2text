import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { ApiError, api } from "../../api/client";
import type { AdminSettingsPut } from "../../api/types";
import { mapApiError } from "../../lib/errors";
import { translate, useT } from "../../i18n";
import Badge from "../../components/ui/Badge";
import Button from "../../components/ui/Button";
import Card from "../../components/ui/Card";
import Input from "../../components/ui/Input";

/** Plan S — "Hệ thống": runtime override cho scheduler/kaggle (bảng Setting),
 * áp dụng live, không restart. Label trên / helper dưới; badge nguồn db|env
 * bên phải mỗi ô. kaggle_mode read-only trên API (đổi mode cần restart). */

type FieldKey =
  | "scheduler_interval_seconds"
  | "kaggle_min_queue"
  | "kaggle_min_gap_seconds";

type StringFieldKey =
  | "llm_base_url"
  | "llm_model"
  | "proofread_llm_model";

const STRING_FIELDS: {
  key: StringFieldKey;
  slug: string;
  labelKey: string;
  helperKey: string;
}[] = [
  {
    key: "llm_base_url",
    slug: "llm-base-url",
    labelKey: "admin.settings.llmBaseUrl",
    helperKey: "admin.settings.llmBaseUrlHelp",
  },
  {
    key: "llm_model",
    slug: "llm-model",
    labelKey: "admin.settings.llmModel",
    helperKey: "admin.settings.llmModelHelp",
  },
  {
    key: "proofread_llm_model",
    slug: "proofread-llm-model",
    labelKey: "admin.settings.proofreadModel",
    helperKey: "admin.settings.proofreadModelHelp",
  },
];

const FIELDS: {
  key: FieldKey;
  slug: string;
  labelKey: string;
  helperKey: string;
  floor: number;
  floorMessageKey: string;
}[] = [
  {
    key: "scheduler_interval_seconds",
    slug: "scheduler-interval",
    labelKey: "admin.settings.schedulerInterval",
    helperKey: "admin.settings.schedulerIntervalHelp",
    floor: 5,
    floorMessageKey: "admin.settings.schedulerIntervalFloor",
  },
  {
    key: "kaggle_min_queue",
    slug: "kaggle-min-queue",
    labelKey: "admin.settings.kaggleMinQueue",
    helperKey: "admin.settings.kaggleMinQueueHelp",
    floor: 1,
    floorMessageKey: "admin.settings.kaggleMinQueueFloor",
  },
  {
    key: "kaggle_min_gap_seconds",
    slug: "kaggle-min-gap",
    labelKey: "admin.settings.kaggleMinGap",
    helperKey: "admin.settings.kaggleMinGapHelp",
    floor: 60,
    floorMessageKey: "admin.settings.kaggleMinGapFloor",
  },
];

export default function AdminSettings() {
  const { t } = useT();
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["admin-settings"],
    queryFn: api.getAdminSettings,
  });
  const [errors, setErrors] = useState<Partial<Record<FieldKey | StringFieldKey, string>>>({});

  const save = useMutation({
    mutationFn: (payload: AdminSettingsPut) => api.putAdminSettings(payload),
    onSuccess: () => {
      toast.success(translate("editor.saved"));
      qc.invalidateQueries({ queryKey: ["admin-settings"] });
    },
    onError: (err) => {
      // server floor message → inline under the field it names
      const detail = err instanceof ApiError ? err.detail : "";
      const hit = FIELDS.find((f) => detail.includes(f.key));
      setErrors(hit ? { [hit.key]: detail } : {});
      toast.error(mapApiError(err));
    },
  });

  function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const payload: AdminSettingsPut = {};
    const next: Partial<Record<FieldKey | StringFieldKey, string>> = {};
    for (const f of FIELDS) {
      const n = Number.parseInt(String(fd.get(f.key) ?? ""), 10);
      if (!Number.isFinite(n)) {
        next[f.key] = t("admin.settings.intRequired");
      } else if (n < f.floor) {
        next[f.key] = t(f.floorMessageKey);
      } else {
        payload[f.key] = n;
      }
    }
    for (const f of STRING_FIELDS) {
      const v = String(fd.get(f.key) ?? "").trim();
      if (v) {
        payload[f.key] = v;
      }
    }
    setErrors(next);
    if (Object.keys(next).length > 0) return; // client check — no PUT on invalid
    save.mutate(payload);
  }

  if (isLoading || !data) {
    return (
      <Card title={t("admin.tab.settings")} testid="card-settings">
        <div data-testid="settings-loading" aria-busy="true" className="p-4 text-sm text-muted">
          {t("common.loading")}
        </div>
      </Card>
    );
  }

  const mode = data.kaggle_mode;
  return (
    <Card title={t("admin.tab.settings")} testid="card-settings">
      <form onSubmit={onSubmit} noValidate data-testid="form-settings" className="flex flex-col gap-5">
        <p className="text-sm text-muted">
          {t("admin.settings.intro")}
        </p>
        {FIELDS.map((f) => {
          const cur = data[f.key];
          return (
            <div key={f.key} className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <Input
                  label={t(f.labelKey)}
                  testid={`input-${f.slug}`}
                  name={f.key}
                  type="number"
                  inputMode="numeric"
                  min={f.floor}
                  defaultValue={String(cur?.value ?? "")}
                  helper={t(f.helperKey) + " " + t("admin.settings.current", { value: cur?.value ?? "", source: cur?.source ?? "" })}
                  error={errors[f.key]}
                />
              </div>
              <Badge
                testid={`source-${f.slug}`}
                tone={cur?.source === "db" ? "info" : "neutral"}
              >
                {cur?.source}
              </Badge>
            </div>
          );
        })}
        {STRING_FIELDS.map((f) => {
          const cur = data[f.key];
          return (
            <div key={f.key} className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <Input
                  label={t(f.labelKey)}
                  testid={`input-${f.slug}`}
                  name={f.key}
                  type="text"
                  defaultValue={String(cur?.value ?? "")}
                  helper={t(f.helperKey) + " " + t("admin.settings.current", { value: cur?.value ?? "", source: cur?.source ?? "" })}
                  error={errors[f.key]}
                />
              </div>
              <Badge
                testid={`source-${f.slug}`}
                tone={cur?.source === "db" ? "info" : "neutral"}
              >
                {cur?.source}
              </Badge>
            </div>
          );
        })}
        <div className="flex flex-col gap-1 text-sm">
          <div className="flex items-center gap-2">
            <span className="text-muted">{t("admin.settings.kaggleMode")}</span>
            <span data-testid="kaggle-mode-value" className="font-mono">
              {String(mode?.value ?? "")}
            </span>
            <Badge
              testid="source-kaggle-mode"
              tone={mode?.source === "db" ? "info" : "neutral"}
            >
              {mode?.source}
            </Badge>
          </div>
          <p className="text-sm text-muted">
            {t("admin.settings.kaggleModeHelp")}
          </p>
        </div>
        <div>
          <Button
            type="submit"
            testid="btn-save-settings"
            loading={save.isPending}
          >
            {t("common.save")}
          </Button>
        </div>
      </form>
    </Card>
  );
}
