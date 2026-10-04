import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError, api } from "../api/client";

export default function MarkdownEditor({ jobId, initial }: { jobId: string; initial: string }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const save = async () => {
    setError(null);
    try {
      await api.patchContent(jobId, value);
      setEditing(false);
      // Binding (T5 ledger): invalidate job query or preview shows stale
      // edited_markdown (polling stopped at done).
      await queryClient.invalidateQueries({ queryKey: ["job", jobId] });
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Lưu thất bại.");
    }
  };

  return (
    <section className="mt-4">
      {error && (
        <div
          data-testid="editor-error"
          className="mb-2 rounded border border-red-300 bg-red-50 px-3 py-2 text-red-700"
        >
          {error}
        </div>
      )}
      {editing && (
        <textarea
          data-testid="textarea-markdown"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="mb-2 h-64 w-full rounded border p-2 font-mono text-sm"
        />
      )}
      <div className="flex gap-2">
        {editing ? (
          <button
            type="button"
            data-testid="btn-save"
            onClick={save}
            className="rounded bg-blue-600 px-4 py-2 text-white hover:bg-blue-700"
          >
            Lưu
          </button>
        ) : (
          <button
            type="button"
            data-testid="btn-edit"
            onClick={() => {
              setValue(initial);
              setError(null);
              setEditing(true);
            }}
            className="rounded bg-blue-600 px-4 py-2 text-white hover:bg-blue-700"
          >
            Chỉnh sửa
          </button>
        )}
      </div>
    </section>
  );
}
