import { useMutation, useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { api } from "../api/client";

/** POST /api/jobs returns a partial job; callers only need `id` for routing. */
export default function UploadButton({
  onUploaded,
}: { onUploaded: (job: { id: number; status: string }) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const { data: me } = useQuery({ queryKey: ["me"], queryFn: api.me });
  const granted = me?.ocr_enabled ?? false;
  // ponytail: gate only after me resolves — avoids disabled-button race in tests; server enforces anyway
  const denied = me !== undefined && !granted;

  const upload = useMutation({
    mutationFn: (file: File) => api.uploadJob(file),
    onMutate: () => setBusy(true),
    onSuccess: (job) => onUploaded(job),
    onSettled: () => setBusy(false),
  });

  return (
    <div>
      {denied && (
        <div
          data-testid="banner-no-access"
          className="mb-2 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-amber-800"
        >
          Chờ admin cấp quyền
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
          const file = e.target.files?.[0];
          if (file) upload.mutate(file);
          e.target.value = "";
        }}
      />
      <button
        type="button"
        data-testid="btn-upload"
        disabled={busy || denied}
        onClick={() => inputRef.current?.click()}
        className="rounded bg-blue-600 px-4 py-2 text-white hover:bg-blue-700 disabled:opacity-50"
      >
        Tải file lên
      </button>
    </div>
  );
}
