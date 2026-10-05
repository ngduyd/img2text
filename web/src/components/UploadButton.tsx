import { useMutation, useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { ApiError, api } from "../api/client";
import Button from "./ui/Button";

/** POST /api/jobs returns a partial job; callers only need `id` for routing. */
export default function UploadButton({
  onUploaded,
}: { onUploaded: (job: { id: number; status: string }) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me });
  const granted = me?.ocr_enabled ?? false;
  // ponytail: gate only after me resolves — avoids disabled-button race in tests; server enforces anyway
  const denied = me !== undefined && !granted;

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

  return (
    <div>
      {denied && (
        <div
          data-testid="banner-no-access"
          className="mb-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2 text-warning"
        >
          Chờ admin cấp quyền
        </div>
      )}
      {error && (
        <div
          data-testid="upload-error"
          className="mb-2 rounded-lg border border-error/40 bg-error/10 px-3 py-2 text-error"
        >
          {error}
        </div>
      )}
      <input
        ref={inputRef}
        type="file"
        data-testid="input-file"
        accept="image/jpeg,image/png,image/webp,application/pdf"
        className="hidden"
        disabled={busy || denied}
        onChange={(e) => {
          setError(null);
          const file = e.target.files?.[0];
          if (file) upload.mutate(file);
          e.target.value = "";
        }}
      />
      <Button
        testid="btn-upload"
        disabled={busy || denied}
        loading={busy}
        onClick={() => inputRef.current?.click()}
      >
        Tải file lên
      </Button>
    </div>
  );
}
