import { useState } from "react";
import type { JobMode } from "../api/types";
import Button from "./ui/Button";

/** output_format server nhận: "md" | "docx" (jobs.py). */
export type SubmitFormat = "md" | "docx";

/** Spec U3: modal lúc Gửi — mode (extract_only | layout) + md/word (chỉ khi layout). */
export default function SubmitModal({
  open,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  onConfirm: (choice: { mode: JobMode; output_format: SubmitFormat }) => void;
  onCancel: () => void;
}) {
  const [mode, setMode] = useState<JobMode>("layout");
  const [format, setFormat] = useState<SubmitFormat>("md");
  if (!open) return null;
  return (
    <div
      data-testid="submit-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    >
      <div className="w-full max-w-sm rounded-card border border-border bg-surface p-4 text-left">
        <fieldset className="mb-3">
          <legend className="mb-2 text-sm font-medium">Chế độ xử lý</legend>
          <label className="mr-4 inline-flex cursor-pointer items-center gap-1.5 text-sm">
            <input
              type="radio"
              name="sm-mode"
              data-testid="sm-mode-extract-only"
              checked={mode === "extract_only"}
              onChange={() => setMode("extract_only")}
              className="accent-accent"
            />
            Lấy văn bản
          </label>
          <label className="inline-flex cursor-pointer items-center gap-1.5 text-sm">
            <input
              type="radio"
              name="sm-mode"
              data-testid="sm-mode-layout"
              checked={mode === "layout"}
              onChange={() => setMode("layout")}
              className="accent-accent"
            />
            Lấy cả layout
          </label>
        </fieldset>
        {mode === "layout" && (
          <fieldset className="mb-4">
            <legend className="mb-2 text-sm font-medium">Định dạng</legend>
            {(["md", "docx"] as const).map((f) => (
              <label key={f} className="mr-4 inline-flex cursor-pointer items-center gap-1.5 text-sm">
                <input
                  type="radio"
                  name="sm-format"
                  data-testid={`sm-format-${f}`}
                  checked={format === f}
                  onChange={() => setFormat(f)}
                  className="accent-accent"
                />
                {f === "md" ? "md" : "word"}
              </label>
            ))}
          </fieldset>
        )}
        <div className="flex justify-end gap-2">
          <Button testid="sm-cancel" variant="ghost" onClick={onCancel}>
            Hủy
          </Button>
          <Button
            testid="sm-confirm"
            onClick={() => onConfirm({ mode, output_format: mode === "extract_only" ? "md" : format })}
          >
            Gửi
          </Button>
        </div>
      </div>
    </div>
  );
}
