import type { JobMode } from "../api/types";

/** Phase 5 (spec E): "Lấy layout" (gen md/docx) | "Chỉ trích xuất văn bản" (text only). */
const MODE_LABEL: Record<JobMode, string> = {
  layout: "Lấy layout",
  extract_only: "Chỉ trích xuất văn bản",
};

/** Upload-mode radios — single instance at a time (Dropzone empty state OR wizard). */
export default function ModeSelector({
  mode,
  onModeChange,
}: {
  mode?: JobMode;
  onModeChange?: (mode: JobMode) => void;
}) {
  const current = mode === "extract_only" ? "extract_only" : "layout";
  return (
    <fieldset data-testid="mode-selector" className="flex items-center gap-4">
      <legend className="sr-only">Chế độ xử lý</legend>
      {(Object.keys(MODE_LABEL) as JobMode[]).map((m) => (
        <label
          key={m}
          className="inline-flex cursor-pointer items-center gap-1.5 text-sm text-text"
        >
          <input
            type="radio"
            name="upload-mode"
            data-testid={`mode-${m.replace("_", "-")}`}
            checked={current === m}
            onChange={() => onModeChange?.(m)}
            className="accent-accent"
          />
          {MODE_LABEL[m]}
        </label>
      ))}
    </fieldset>
  );
}
