import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { loadPdf } from "../lib/pdfjs";
import Button from "./ui/Button";
import { useDialogA11y } from "./ui/useDialogA11y";

/** Entry MultiFileUpload truyền vào dialog chọn trang (1-based). */
export interface PageSelectEntry {
  name: string;
  numPages: number;
  pages: number[];
  blob: Blob;
}

/**
 * Spec U4: chọn số trang per-PDF — checkbox grid + thumbnail (pdf.js) → mảng trang.
 * MultiFileUpload tự chặn deselect-all + cap 25 trang.
 */
export default function PageSelectDialog({
  entry,
  onCancel,
  onDone,
}: {
  entry: PageSelectEntry;
  onCancel: () => void;
  onDone: (pages: number[]) => void;
}) {
  const [selected, setSelected] = useState<number[]>(
    entry.pages.length > 0 ? entry.pages : Array.from({ length: entry.numPages }, (_, i) => i + 1),
  );
  const canvasRefs = useRef<Array<HTMLCanvasElement | null>>([]);
  const panelRef = useDialogA11y<HTMLDivElement>(true, onCancel);

  // Thumbnail render sau mount (refs đã gắn) — cancel flag chặn setState sau unmount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const doc = await loadPdf(entry.blob);
        for (let n = 1; n <= entry.numPages; n++) {
          const canvas = canvasRefs.current[n - 1];
          if (!canvas || cancelled) continue;
          const page = await doc.getPage(n);
          await page.renderCanvas(canvas);
        }
      } catch {
        // Đã validate lúc thêm file — hiếm khi fail; bỏ thumbnail, giữ chọn trang.
        if (!cancelled) toast.error("Không đọc được trang xem trước.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [entry]);

  const toggle = (n: number) =>
    setSelected((prev) => (prev.includes(n) ? prev.filter((x) => x !== n) : [...prev, n].sort((a, b) => a - b)));

  return (
    <div
      data-testid="pages-dialog"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="pages-dialog-title"
        tabIndex={-1}
        className="w-full max-w-lg rounded-card border border-border bg-surface p-4 text-left outline-none"
      >
        <p id="pages-dialog-title" className="mb-2 text-sm font-medium">
          Chọn số trang · {entry.name}
        </p>
        <div
          data-testid="pages-grid"
          className="mb-4 mt-2 grid max-h-[60vh] grid-cols-3 gap-2 overflow-auto sm:grid-cols-4"
        >
          {Array.from({ length: entry.numPages }, (_, i) => i + 1).map((n) => {
            const on = selected.includes(n);
            return (
              <button
                key={n}
                type="button"
                data-testid={`pages-check-${n}`}
                aria-pressed={on}
                onClick={() => toggle(n)}
                className={`rounded-md border p-1 text-xs ${
                  on ? "border-accent bg-accent/15 text-accent-text" : "border-border bg-surface-2 text-muted"
                }`}
              >
                <canvas
                  ref={(el) => {
                    canvasRefs.current[n - 1] = el;
                  }}
                  className="mb-1 h-auto w-full bg-white"
                />
                <span>Trang {n}</span>
              </button>
            );
          })}
        </div>
        <div className="flex justify-end gap-2">
          <Button testid="pages-cancel" variant="ghost" onClick={onCancel}>
            Hủy
          </Button>
          <Button testid="pages-confirm" onClick={() => onDone(selected)}>
            Chọn {selected.length} trang
          </Button>
        </div>
      </div>
    </div>
  );
}
