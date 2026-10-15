import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { ApiError, api } from "../../api/client";
import type { AdminSettingEntry, AdminSettingsPut, LlmTestResult } from "../../api/types";
import { mapApiError } from "../../lib/errors";
import { translate, useT } from "../../i18n";
import Badge from "../../components/ui/Badge";
import Button from "../../components/ui/Button";
import Card from "../../components/ui/Card";
import Input from "../../components/ui/Input";

/** Lane CFG — "Hệ thống": TOÀN BỘ cấu hình động chia 5 section (LLM / Kaggle
 * GPU / Scheduler / Giới hạn / SMTP). Mỗi ô: label + help + nguồn badge
 * (db|env) + nút Reset (DELETE row → về env). Nút Test cạnh mỗi ô model gọi
 * test-model → badge Sống/Chết + latency. Save từng section (payload chỉ gồm
 * field section đó) + Save all. upload_byte_limit nhập/hiển thị theo MB
 * (1 MB = 1048576 B — khớp floor server). Ô secret (llm_api_key, smtp_pass)
 * không prefill mask; để trống = không PUT (giữ giá trị hiện tại). */

type SectionId = "llm" | "kaggle" | "scheduler" | "limits" | "smtp";

interface FieldDef {
  key: keyof AdminSettingsPut & string;
  slug: string;
  section: SectionId;
  kind: "int" | "str";
  labelKey: string;
  helperKey: string;
  floor?: number;
  floorMessageKey?: string;
  ceiling?: number;
  ceilingMessageKey?: string;
  /** input/hiển thị theo MB, lưu theo bytes */
  unitMb?: boolean;
  /** write-only: không prefill, ô trống = không PUT */
  secret?: boolean;
  /** có nút Test → gọi /api/admin/llm/test-model */
  testModel?: boolean;
}

const MB = 1048576;

const FIELDS: FieldDef[] = [
  // LLM
  { key: "llm_base_url", slug: "llm-base-url", section: "llm", kind: "str",
    labelKey: "admin.settings.llmBaseUrl", helperKey: "admin.settings.llmBaseUrlHelp" },
  { key: "llm_model", slug: "llm-model", section: "llm", kind: "str",
    labelKey: "admin.settings.llmModel", helperKey: "admin.settings.llmModelHelp", testModel: true },
  { key: "ir_llm_model", slug: "ir-llm-model", section: "llm", kind: "str",
    labelKey: "admin.settings.irModel", helperKey: "admin.settings.irModelHelp", testModel: true },
  { key: "proofread_llm_model", slug: "proofread-llm-model", section: "llm", kind: "str",
    labelKey: "admin.settings.proofreadModel", helperKey: "admin.settings.proofreadModelHelp", testModel: true },
  { key: "llm_api_key", slug: "llm-api-key", section: "llm", kind: "str", secret: true,
    labelKey: "admin.settings.llmApiKey", helperKey: "admin.settings.llmApiKeyHelp" },
  { key: "llm_timeout", slug: "llm-timeout", section: "llm", kind: "int",
    labelKey: "admin.settings.llmTimeout", helperKey: "admin.settings.llmTimeoutHelp",
    floor: 120, floorMessageKey: "admin.settings.llmTimeoutFloor",
    ceiling: 600, ceilingMessageKey: "admin.settings.llmTimeoutCeiling" },
  // Kaggle GPU
  { key: "kaggle_min_queue", slug: "kaggle-min-queue", section: "kaggle", kind: "int",
    labelKey: "admin.settings.kaggleMinQueue", helperKey: "admin.settings.kaggleMinQueueHelp",
    floor: 1, floorMessageKey: "admin.settings.kaggleMinQueueFloor" },
  { key: "kaggle_min_gap_seconds", slug: "kaggle-min-gap", section: "kaggle", kind: "int",
    labelKey: "admin.settings.kaggleMinGap", helperKey: "admin.settings.kaggleMinGapHelp",
    floor: 60, floorMessageKey: "admin.settings.kaggleMinGapFloor" },
  // Scheduler
  { key: "scheduler_interval_seconds", slug: "scheduler-interval", section: "scheduler", kind: "int",
    labelKey: "admin.settings.schedulerInterval", helperKey: "admin.settings.schedulerIntervalHelp",
    floor: 5, floorMessageKey: "admin.settings.schedulerIntervalFloor" },
  { key: "purge_interval_seconds", slug: "purge-interval", section: "scheduler", kind: "int",
    labelKey: "admin.settings.purgeInterval", helperKey: "admin.settings.purgeIntervalHelp",
    floor: 60, floorMessageKey: "admin.settings.purgeIntervalFloor" },
  // Giới hạn
  { key: "max_pages", slug: "max-pages", section: "limits", kind: "int",
    labelKey: "admin.settings.maxPages", helperKey: "admin.settings.maxPagesHelp",
    floor: 1, floorMessageKey: "admin.settings.maxPagesFloor" },
  { key: "daily_page_limit", slug: "daily-page-limit", section: "limits", kind: "int",
    labelKey: "admin.settings.dailyLimit", helperKey: "admin.settings.dailyLimitHelp",
    floor: 0, floorMessageKey: "admin.settings.nonNegative" },
  { key: "weekly_page_limit", slug: "weekly-page-limit", section: "limits", kind: "int",
    labelKey: "admin.settings.weeklyLimit", helperKey: "admin.settings.weeklyLimitHelp",
    floor: 0, floorMessageKey: "admin.settings.nonNegative" },
  { key: "upload_byte_limit", slug: "upload-byte-limit", section: "limits", kind: "int", unitMb: true,
    labelKey: "admin.settings.uploadByteLimit", helperKey: "admin.settings.uploadByteLimitHelp",
    floor: 1, floorMessageKey: "admin.settings.uploadByteLimitFloor" },
  { key: "purge_retention_days", slug: "purge-retention", section: "limits", kind: "int",
    labelKey: "admin.settings.purgeRetention", helperKey: "admin.settings.purgeRetentionHelp",
    floor: 1, floorMessageKey: "admin.settings.purgeRetentionFloor" },
  // SMTP
  { key: "smtp_host", slug: "smtp-host", section: "smtp", kind: "str",
    labelKey: "admin.settings.smtpHost", helperKey: "admin.settings.smtpHostHelp" },
  { key: "smtp_port", slug: "smtp-port", section: "smtp", kind: "int",
    labelKey: "admin.settings.smtpPort", helperKey: "admin.settings.smtpPortHelp",
    floor: 1, floorMessageKey: "admin.settings.smtpPortRange",
    ceiling: 65535, ceilingMessageKey: "admin.settings.smtpPortRange" },
  { key: "smtp_user", slug: "smtp-user", section: "smtp", kind: "str",
    labelKey: "admin.settings.smtpUser", helperKey: "admin.settings.smtpUserHelp" },
  { key: "smtp_pass", slug: "smtp-pass", section: "smtp", kind: "str", secret: true,
    labelKey: "admin.settings.smtpPass", helperKey: "admin.settings.smtpPassHelp" },
  { key: "smtp_from", slug: "smtp-from", section: "smtp", kind: "str",
    labelKey: "admin.settings.smtpFrom", helperKey: "admin.settings.smtpFromHelp" },
];

const SECTIONS: { id: SectionId; titleKey: string }[] = [
  { id: "llm", titleKey: "admin.settings.sectionLlm" },
  { id: "kaggle", titleKey: "admin.settings.sectionKaggle" },
  { id: "scheduler", titleKey: "admin.settings.sectionScheduler" },
  { id: "limits", titleKey: "admin.settings.sectionLimits" },
  { id: "smtp", titleKey: "admin.settings.sectionSmtp" },
];

/** Giá trị hiển thị trong helper/current (MB đổi về MB, secret → mask). */
function displayValue(f: FieldDef, cur: AdminSettingEntry | undefined): string {
  const v = cur?.value;
  if (v == null || v === "") return translate("admin.settings.unset");
  if (f.unitMb) return `${Math.round(Number(v) / MB)} MB`;
  return String(v);
}

/** defaultValue cho input — secret luôn rỗng (không prefill mask). */
function defaultValueOf(f: FieldDef, cur: AdminSettingEntry | undefined): string {
  if (f.secret) return "";
  const v = cur?.value;
  if (v == null) return "";
  if (f.unitMb) return String(Math.round(Number(v) / MB));
  return String(v);
}

export default function AdminSettings() {
  const { t } = useT();
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["admin-settings"],
    queryFn: api.getAdminSettings,
  });
  const formRef = useRef<HTMLFormElement>(null);
  const [errors, setErrors] = useState<Partial<Record<string, string>>>({});
  const [testing, setTesting] = useState<Partial<Record<string, boolean>>>({});
  const [results, setResults] = useState<Partial<Record<string, LlmTestResult>>>({});

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

  /** Validate + PUT. section=null → Save all; có section → chỉ field section đó. */
  function saveFields(section: SectionId | null) {
    const form = formRef.current;
    if (!form) return;
    const fd = new FormData(form);
    const fields = section ? FIELDS.filter((f) => f.section === section) : FIELDS;
    // widen qua Record — f.key là union keyof (string|number field lẫn nhau)
    const payload: AdminSettingsPut = {};
    const out = payload as Record<string, string | number | undefined>;
    const next: Partial<Record<string, string>> = {};
    for (const f of fields) {
      const raw = String(fd.get(f.key) ?? "").trim();
      if (f.kind === "str") {
        // ô trống = không PUT (write-only giữ nguyên / giữ env)
        if (raw) out[f.key] = raw;
        continue;
      }
      if (!/^-?\d+$/.test(raw)) {
        next[f.key] = t("admin.settings.intRequired");
        continue;
      }
      const n = Number.parseInt(raw, 10);
      if (f.floor !== undefined && n < f.floor) {
        next[f.key] = t(f.floorMessageKey!);
      } else if (f.ceiling !== undefined && n > f.ceiling) {
        next[f.key] = t(f.ceilingMessageKey!);
      } else {
        out[f.key] = f.unitMb ? n * MB : n;
      }
    }
    setErrors((prev) => {
      const base = { ...prev };
      for (const f of fields) delete base[f.key];
      return { ...base, ...next };
    });
    if (Object.keys(next).length > 0) return; // client check — no PUT on invalid
    save.mutate(payload);
  }

  /** Reset về env: xóa Setting row (DELETE) → badge nguồn về "env". */
  async function resetField(f: FieldDef) {
    try {
      const next = await api.deleteAdminSetting(f.key);
      qc.setQueryData(["admin-settings"], next);
      toast.success(translate("admin.settings.resetDone"));
    } catch (err) {
      toast.error(mapApiError(err));
    }
  }

  /** Test model: 1 prompt "ping" qua server → badge Sống/Chết + latency.
   * P2f: gửi kèm base_url đang nhập trong form — probe đúng URL admin sửa
   * (chưa lưu vẫn test được, không phải lưu trước). */
  async function runTest(f: FieldDef) {
    const form = formRef.current;
    if (!form) return;
    const fd = new FormData(form);
    const model = String(fd.get(f.key) ?? "").trim();
    if (!model) return;
    const baseUrl = String(fd.get("llm_base_url") ?? "").trim();
    setTesting((s) => ({ ...s, [f.key]: true }));
    try {
      const res = await api.testLlmModel({
        model,
        ...(baseUrl ? { base_url: baseUrl } : {}),
      });
      setResults((s) => ({ ...s, [f.key]: res }));
    } catch (err) {
      setResults((s) => ({
        ...s,
        [f.key]: { ok: false, latency_ms: 0, model, error: mapApiError(err) },
      }));
    } finally {
      setTesting((s) => ({ ...s, [f.key]: false }));
    }
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
      <form
        ref={formRef}
        onSubmit={(e) => {
          e.preventDefault();
          saveFields(null);
        }}
        noValidate
        data-testid="form-settings"
        className="flex flex-col gap-5"
      >
        <p className="text-sm text-muted">{t("admin.settings.intro")}</p>

        {SECTIONS.map((sec) => {
          const secFields = FIELDS.filter((f) => f.section === sec.id);
          return (
            <section
              key={sec.id}
              aria-label={t(sec.titleKey)}
              className="flex flex-col gap-4 border-t border-border pt-4 first:border-t-0 first:pt-0"
            >
              <div className="flex items-center justify-between gap-3">
                <h3 className="text-base font-semibold" data-testid={`section-${sec.id}`}>
                  {t(sec.titleKey)}
                </h3>
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  testid={`btn-save-${sec.id}`}
                  loading={save.isPending}
                  onClick={() => saveFields(sec.id)}
                >
                  {t("common.save")}
                </Button>
              </div>

              {secFields.map((f) => {
                const cur = data[f.key];
                const res = results[f.key];
                return (
                  <div key={f.key} className="flex flex-col gap-2">
                    <div className="flex items-end gap-2">
                      <div className="min-w-0 flex-1">
                        <Input
                          label={t(f.labelKey)}
                          testid={`input-${f.slug}`}
                          // key đổi theo giá trị server → reset ô sau save/reset
                          key={`${f.key}:${String(cur?.value ?? "")}:${cur?.source ?? ""}`}
                          name={f.key}
                          type={f.secret ? "password" : f.kind === "int" ? "number" : "text"}
                          inputMode={f.kind === "int" ? "numeric" : undefined}
                          min={f.kind === "int" ? f.floor : undefined}
                          max={f.kind === "int" ? f.ceiling : undefined}
                          placeholder={f.secret ? "••••••" : undefined}
                          defaultValue={defaultValueOf(f, cur)}
                          helper={
                            t(f.helperKey) +
                            " " +
                            t("admin.settings.current", {
                              value: displayValue(f, cur),
                              source: cur?.source ?? "",
                            })
                          }
                          error={errors[f.key]}
                        />
                      </div>
                      <div className="flex items-center gap-2 pb-1">
                        {f.testModel && (
                          <Button
                            type="button"
                            variant="secondary"
                            size="sm"
                            testid={`test-${f.slug}`}
                            loading={testing[f.key]}
                            onClick={() => runTest(f)}
                          >
                            {t("admin.settings.test")}
                          </Button>
                        )}
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          testid={`reset-${f.slug}`}
                          onClick={() => resetField(f)}
                        >
                          {t("admin.settings.reset")}
                        </Button>
                        <Badge
                          testid={`source-${f.slug}`}
                          tone={cur?.source === "db" ? "info" : "neutral"}
                        >
                          {cur?.source}
                        </Badge>
                      </div>
                    </div>
                    {f.testModel && res && (
                      <div
                        className="flex flex-wrap items-center gap-2 text-xs"
                        data-testid={`test-result-${f.slug}`}
                      >
                        <Badge tone={res.ok ? "success" : "error"}>
                          {res.ok
                            ? t("admin.settings.testAlive", { ms: res.latency_ms })
                            : t("admin.settings.testDead")}
                        </Badge>
                        {!res.ok && res.error && (
                          <span className="text-error">{res.error}</span>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}

              {sec.id === "kaggle" && (
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
                  <p className="text-sm text-muted">{t("admin.settings.kaggleModeHelp")}</p>
                </div>
              )}
            </section>
          );
        })}

        <div>
          <Button type="submit" testid="btn-save-settings" loading={save.isPending}>
            {t("common.saveAll")}
          </Button>
        </div>
      </form>
    </Card>
  );
}
