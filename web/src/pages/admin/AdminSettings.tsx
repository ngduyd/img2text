import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { ApiError, api } from "../../api/client";
import type { AdminSettingsPut } from "../../api/types";
import { mapApiError } from "../../lib/errors";
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
  label: string;
  helper: string;
}[] = [
  {
    key: "llm_base_url",
    slug: "llm-base-url",
    label: "Địa chỉ LLM",
    helper: "Endpoint OpenAI-compatible (vd http://localhost:20128/v1).",
  },
  {
    key: "llm_model",
    slug: "llm-model",
    label: "Model layout",
    helper: "Model dùng cho md-layout + docx-layout.",
  },
  {
    key: "proofread_llm_model",
    slug: "proofread-llm-model",
    label: "Model kiểm tra từ",
    helper: "Model dùng cho proofread (gợi ý sửa lỗi OCR).",
  },
];

const FIELDS: {
  key: FieldKey;
  slug: string;
  label: string;
  helper: string;
  floor: number;
  floorMessage: string;
}[] = [
  {
    key: "scheduler_interval_seconds",
    slug: "scheduler-interval",
    label: "Chu kỳ scheduler (giây)",
    helper: "Sweep reap-leases; mặc định 60, tối thiểu 5.",
    floor: 5,
    floorMessage: "scheduler_interval_seconds phải từ 5 giây trở lên.",
  },
  {
    key: "kaggle_min_queue",
    slug: "kaggle-min-queue",
    label: "Kaggle min queue",
    helper: "Số job chờ tối thiểu để spawn (mode loop); mặc định 1.",
    floor: 1,
    floorMessage: "kaggle_min_queue phải từ 1 trở lên.",
  },
  {
    key: "kaggle_min_gap_seconds",
    slug: "kaggle-min-gap",
    label: "Kaggle min gap (giây)",
    helper: "Khoảng cách tối thiểu giữa 2 lần spawn; mặc định 600.",
    floor: 60,
    floorMessage: "kaggle_min_gap_seconds phải từ 60 giây trở lên.",
  },
];

export default function AdminSettings() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["admin-settings"],
    queryFn: api.getAdminSettings,
  });
  const [errors, setErrors] = useState<Partial<Record<FieldKey | StringFieldKey, string>>>({});

  const save = useMutation({
    mutationFn: (payload: AdminSettingsPut) => api.putAdminSettings(payload),
    onSuccess: () => {
      toast.success("Đã lưu.");
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
        next[f.key] = "Giá trị phải là số nguyên.";
      } else if (n < f.floor) {
        next[f.key] = f.floorMessage;
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
      <Card title="Hệ thống" testid="card-settings">
        <div data-testid="settings-loading" aria-busy="true" className="p-4 text-sm text-muted">
          Đang tải…
        </div>
      </Card>
    );
  }

  const mode = data.kaggle_mode;
  return (
    <Card title="Hệ thống" testid="card-settings">
      <form onSubmit={onSubmit} noValidate data-testid="form-settings" className="flex flex-col gap-5">
        <p className="text-sm text-muted">
          Giá trị lưu vào bảng <span className="font-mono">Setting</span> (runtime
          override) — áp dụng ngay, không cần restart container; khi DB trống thì
          dùng giá trị từ env.
        </p>
        {FIELDS.map((f) => {
          const cur = data[f.key];
          return (
            <div key={f.key} className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <Input
                  label={f.label}
                  testid={`input-${f.slug}`}
                  name={f.key}
                  type="number"
                  inputMode="numeric"
                  min={f.floor}
                  defaultValue={String(cur?.value ?? "")}
                  helper={`${f.helper} Hiện tại: ${cur?.value} (${cur?.source}).`}
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
                  label={f.label}
                  testid={`input-${f.slug}`}
                  name={f.key}
                  type="text"
                  defaultValue={String(cur?.value ?? "")}
                  helper={`${f.helper} Hiện tại: ${cur?.value} (${cur?.source}).`}
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
            <span className="text-muted">Chế độ Kaggle (kaggle_mode):</span>
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
            read-only trên API — thay đổi mode cần restart container.
          </p>
        </div>
        <div>
          <Button
            type="submit"
            testid="btn-save-settings"
            loading={save.isPending}
          >
            Lưu
          </Button>
        </div>
      </form>
    </Card>
  );
}
