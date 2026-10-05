import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ApiError, api } from "../api/client";
import { mapApiError } from "../lib/errors";
import Button from "./ui/Button";

export default function MarkdownEditor({ jobId, initial }: { jobId: string; initial: string }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const save = async () => {
    setError(null);
    try {
      await api.patchContent(jobId, value);
      toast.success("Đã lưu.");
      setEditing(false);
      // Binding (T5 ledger): invalidate job query or preview shows stale
      // edited_markdown (polling stopped at done).
      await queryClient.invalidateQueries({ queryKey: ["job", jobId] });
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Lưu thất bại.");
      toast.error(mapApiError(err));
    }
  };

  return (
    <section className="mt-4">
      {error && (
        <div
          data-testid="editor-error"
          className="mb-2 rounded-lg border border-error/40 bg-error/10 px-3 py-2 text-error"
        >
          {error}
        </div>
      )}
      {editing && (
        <textarea
          data-testid="textarea-markdown"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="mb-2 h-64 w-full rounded-lg border border-border bg-surface p-2 font-mono text-sm text-text"
        />
      )}
      <div className="flex gap-2">
        {editing ? (
          <Button testid="btn-save" onClick={save}>
            Lưu
          </Button>
        ) : (
          <Button
            testid="btn-edit"
            onClick={() => {
              setValue(initial);
              setError(null);
              setEditing(true);
            }}
          >
            Chỉnh sửa
          </Button>
        )}
      </div>
    </section>
  );
}
