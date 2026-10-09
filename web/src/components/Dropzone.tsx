import { useMutation, useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { ApiError, api } from "../api/client";
import { mapApiError } from "../lib/errors";
import PdfWizard from "./wizard/PdfWizard";
import ImageCropWizard from "./wizard/ImageCropWizard";
import FormatSplitButton, { type OutputFormat } from "./FormatSplitButton";

/** POST /api/jobs returns a partial job; callers only need `id` for routing. */
export default function Dropzone({
  outputFormat = "md",
  onFormatChange,
  onUploaded,
}: {
  /** Plan D4: export format chosen on the Jobs page — appended as multipart output_format. */
  outputFormat?: string;
  /** Format combo: caret menu writes back to the Jobs page state (single source of truth). */
  onFormatChange: (format: OutputFormat) => void;
  onUploaded: (job: { id: number; status: string }) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  // pdf/image selection defers to a wizard; other files upload immediately.
  const [wizardFile, setWizardFile] = useState<File | null>(null);
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me });
  const granted = me?.ocr_enabled ?? false;
  // ponytail: gate only after me resolves — avoids disabled-button race in tests; server enforces anyway
  const denied = me !== undefined && !granted;
  const disabled = busy || denied;
  // Remount the wizard per selected file: crop rect/dims, preview bitmap and
  // pdf doc are file-scoped — they must not survive a file swap (stale bytes).
  const wizardKey = wizardFile ? `${wizardFile.name}-${wizardFile.size}-${wizardFile.lastModified}` : null;

  const upload = useMutation({
    mutationFn: (file: File) => api.uploadJob(file, { output_format: outputFormat }),
    onMutate: () => {
      setError(null);
      setBusy(true);
    },
    onSuccess: (job) => {
      // R59: toast + parent navigates to the /jobs list route (see Jobs.tsx onUploaded).
      toast.success("Đã tải lên — đang chờ xử lý.");
      onUploaded(job);
    },
    onError: (err) => {
      // R51: inline block kept; toast mirrors it (R59).
      setError(err instanceof ApiError ? err.detail : "Tải file thất bại.");
      toast.error(mapApiError(err));
    },
    onSettled: () => setBusy(false),
  });

  const handleFile = (file: File | undefined | null) => {
    if (!file || disabled) return;
    if (file.type === "application/pdf" || file.type.startsWith("image/")) {
      setWizardFile(file);
      return;
    }
    upload.mutate(file);
  };

  return (
    <div
      data-testid="dropzone"
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        handleFile(e.dataTransfer?.files?.[0]);
      }}
      className={`rounded-card border-2 border-dashed p-4 text-center transition duration-150 ease-out md:p-6 ${
        dragging
          ? "border-accent bg-accent/10"
          : "border-border bg-surface/50 hover:border-accent/50 hover:bg-surface-2/40"
      }`}
    >
      {denied && (
        <div
          data-testid="banner-no-access"
          className="mb-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-warning"
        >
          Chờ admin cấp quyền
          <p className="mt-1 text-xs">
            Môi trường dev: đăng nhập tài khoản admin → mục Người dùng → bật OCR cho tài khoản
            này.
          </p>
        </div>
      )}
      {error && !wizardFile && (
        <div
          data-testid="upload-error"
          className="mb-2 rounded-md border border-error/40 bg-error/10 px-3 py-2 text-error"
        >
          {error}
        </div>
      )}
      {wizardFile ? (
        wizardFile.type === "application/pdf" ? (
          <PdfWizard
            key={wizardKey}
            file={wizardFile}
            outputFormat={outputFormat}
            onFormatChange={onFormatChange}
            onCancel={() => setWizardFile(null)}
            onUploaded={onUploaded}
          />
        ) : (
          <ImageCropWizard
            key={wizardKey}
            file={wizardFile}
            outputFormat={outputFormat}
            onFormatChange={onFormatChange}
            onCancel={() => setWizardFile(null)}
            onUploaded={onUploaded}
          />
        )
      ) : (
        <>
          <p className="mb-2 text-sm text-muted">Kéo thả file vào đây hoặc chọn từ máy</p>
          <input
            ref={inputRef}
            type="file"
            data-testid="input-file"
            accept="image/jpeg,image/png,image/webp,application/pdf"
            className="hidden"
            disabled={disabled}
            onChange={(e) => {
              setError(null);
              handleFile(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
          <FormatSplitButton
            testid="btn-upload"
            label="Tải file lên"
            format={outputFormat}
            onFormatChange={onFormatChange}
            onClick={() => inputRef.current?.click()}
            disabled={disabled}
            loading={busy}
          />
        </>
      )}
    </div>
  );
}
