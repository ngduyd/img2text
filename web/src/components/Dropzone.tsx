import { useMutation, useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { ApiError, api } from "../api/client";
import PdfWizard from "./wizard/PdfWizard";
import Button from "./ui/Button";

/** POST /api/jobs returns a partial job; callers only need `id` for routing. */
export default function Dropzone({
  onUploaded,
}: { onUploaded: (job: { id: number; status: string }) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  // PDF selection defers to the page wizard; images keep the immediate upload flow.
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me });
  const granted = me?.ocr_enabled ?? false;
  // ponytail: gate only after me resolves — avoids disabled-button race in tests; server enforces anyway
  const denied = me !== undefined && !granted;
  const disabled = busy || denied;

  const upload = useMutation({
    mutationFn: (file: File) => api.uploadJob(file),
    onMutate: () => {
      setError(null);
      setBusy(true);
    },
    onSuccess: (job) => onUploaded(job),
    onError: (err) =>
      setError(err instanceof ApiError ? err.detail : "Tải file thất bại."),
    onSettled: () => setBusy(false),
  });

  const handleFile = (file: File | undefined | null) => {
    if (!file || disabled) return;
    if (file.type === "application/pdf") {
      setPdfFile(file);
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
      className={`rounded-card border-2 border-dashed p-4 text-center ${
        dragging ? "border-accent bg-accent/5" : "border-border"
      }`}
    >
      {denied && (
        <div
          data-testid="banner-no-access"
          className="mb-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-warning"
        >
          Chờ admin cấp quyền
          <p className="mt-1 text-xs">
            Môi trường dev: đăng nhập tài khoản admin → mục Người dùng → bật OCR cho tài khoản
            này.
          </p>
        </div>
      )}
      {error && !pdfFile && (
        <div
          data-testid="upload-error"
          className="mb-2 rounded-lg border border-error/40 bg-error/10 px-3 py-2 text-error"
        >
          {error}
        </div>
      )}
      {pdfFile ? (
        <PdfWizard file={pdfFile} onCancel={() => setPdfFile(null)} onUploaded={onUploaded} />
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
          <Button
            testid="btn-upload"
            disabled={disabled}
            loading={busy}
            onClick={() => inputRef.current?.click()}
          >
            Tải file lên
          </Button>
        </>
      )}
    </div>
  );
}
