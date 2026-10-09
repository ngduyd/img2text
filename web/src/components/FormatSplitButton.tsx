import { ChevronDown } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import Button from "./ui/Button";

export type OutputFormat = "md" | "docx";

/** Menu + label spelling — matches the job list wording ("Đầu ra", JobDetail.tsx). */
export const FORMAT_LABEL: Record<OutputFormat, string> = { md: "Markdown", docx: "Word" };

/** Split button: main part runs the action with the current format, caret ▾ picks the format.
 * Controlled — `format`/`onFormatChange` keep Jobs' `outputFormat` the single source of truth. */
export default function FormatSplitButton({
  label,
  format,
  onFormatChange,
  onClick,
  disabled = false,
  loading = false,
  testid,
  className,
}: {
  /** Main-part text before the format suffix, e.g. "Gửi lên". */
  label: string;
  format: string;
  onFormatChange: (format: OutputFormat) => void;
  onClick: () => void;
  disabled?: boolean;
  loading?: boolean;
  /** Main-part testid (btn-upload / wizard-submit); caret is btn-format-toggle. */
  testid: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLSpanElement>(null);

  // Close on click outside (mousedown anywhere outside the split button).
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const current: OutputFormat = format === "docx" ? "docx" : "md";
  const off = disabled || loading;

  return (
    <span ref={rootRef} className="relative inline-flex">
      <Button
        testid={testid}
        disabled={off}
        loading={loading}
        onClick={onClick}
        className={["rounded-r-none", className].filter(Boolean).join(" ")}
      >
        {label} · {FORMAT_LABEL[current]}
      </Button>
      <Button
        testid="btn-format-toggle"
        disabled={off}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Chọn định dạng đầu ra"
        onClick={() => setOpen((o) => !o)}
        className="rounded-l-none border-l border-accent-contrast/30 px-2"
      >
        <ChevronDown size={14} aria-hidden="true" />
      </Button>
      {open && (
        <div
          role="menu"
          aria-label="Định dạng đầu ra"
          className="absolute left-0 top-full z-30 mt-1 min-w-full rounded-sm border border-border bg-surface py-1 shadow-card"
        >
          {(Object.keys(FORMAT_LABEL) as OutputFormat[]).map((f) => (
            <button
              key={f}
              type="button"
              role="menuitemradio"
              aria-checked={current === f}
              data-testid={`format-opt-${f}`}
              onClick={() => {
                onFormatChange(f);
                setOpen(false);
              }}
              className="block w-full cursor-pointer px-3 py-1.5 text-left text-sm hover:bg-surface-2"
            >
              {FORMAT_LABEL[f]}
            </button>
          ))}
        </div>
      )}
    </span>
  );
}
