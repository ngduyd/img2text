import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Copy } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { api } from "../api/client";
import type { JobStatus } from "../api/types";
import { mapApiError } from "../lib/errors";
import { translate } from "../i18n";
import Button from "./ui/Button";

/**
 * Spec #8: collapsible "IR (JSON)" — lazy fetch GET /jobs/{id}/ir khi mở,
 * pretty JSON trong <pre> + Copy. status ≠ done → ẩn (IR chỉ sinh khi render);
 * fetch lỗi (404/409 chưa render) → alert + ẩn nút copy.
 */
export default function IrViewer({ jobId, status }: { jobId: number | string; status: JobStatus }) {
  const [open, setOpen] = useState(false);
  const { data, isError, error } = useQuery({
    queryKey: ["ir", jobId],
    queryFn: () => api.getIr(jobId),
    enabled: open,
    retry: false,
  });

  if (status !== "done") return null;

  const json = data === undefined ? "" : JSON.stringify(data, null, 2);

  return (
    <section data-testid="ir-viewer" className="mt-4 rounded-card border border-border bg-surface p-3 shadow-card">
      <button
        type="button"
        data-testid="ir-viewer-toggle"
        aria-expanded={open}
        aria-controls="ir-json"
        onClick={() => setOpen((v) => !v)}
        className="flex min-h-9 w-full cursor-pointer items-center justify-between gap-2 text-sm font-semibold text-text focus-visible:outline-2 focus-visible:outline-accent"
      >
        IR (JSON)
        <ChevronDown className={`h-4 w-4 text-muted transition-transform ${open ? "rotate-180" : ""}`} aria-hidden="true" />
      </button>
      {open && (
        <div id="ir-json" className="mt-2">
          {isError && (
            <p role="alert" className="text-sm text-error">
              {mapApiError(error)}
            </p>
          )}
          {data !== undefined && (
            <>
              <pre data-testid="ir-viewer-pre" className="max-h-64 overflow-auto rounded-md bg-surface-2 p-2 font-mono text-xs leading-relaxed text-text">
                {json}
              </pre>
              <Button
                testid="ir-viewer-copy"
                variant="secondary"
                size="sm"
                className="mt-2"
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(json);
                    toast.success(translate("ir.copied"));
                  } catch (err) {
                    toast.error(mapApiError(err));
                  }
                }}
              >
                <Copy className="h-4 w-4" aria-hidden="true" />
                Copy
              </Button>
            </>
          )}
        </div>
      )}
    </section>
  );
}
