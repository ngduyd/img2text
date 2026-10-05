import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { ApiError, api } from "../../api/client";
import { mapApiError } from "../../lib/errors";
import { loadPdf } from "../../lib/pdfjs";
import Button from "../ui/Button";

/** Max pages per upload — server rejects more; client blocks before the call. */
const MAX_PAGES = 50;

interface PageState {
  n: number;
  selected: boolean;
  rotate: number;
  thumb: string | null;
}

export default function PdfWizard({
  file,
  onCancel,
  onUploaded,
}: {
  file: File;
  onCancel: () => void;
  onUploaded: (job: { id: number; status: string }) => void;
}) {
  const [pages, setPages] = useState<PageState[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canvasRefs = useRef<Array<HTMLCanvasElement | null>>([]);
  const docRef = useRef<Awaited<ReturnType<typeof loadPdf>> | null>(null);
  // StrictMode double-effect guard — pdfjs document loaded once per mount
  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    loadPdf(file)
      .then((doc) => {
        docRef.current = doc;
        setPages(
          Array.from({ length: doc.numPages }, (_, i) => ({
            n: i + 1,
            selected: true,
            rotate: 0,
            thumb: null,
          })),
        );
        setLoading(false);
      })
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.detail : "Không đọc được file PDF.");
        setLoading(false);
      });
  }, [file]);

  // Thumbnails: canvases mount with the list; render once, swap to dataURL <img>.
  useEffect(() => {
    const doc = docRef.current;
    if (loading || !doc) return;
    let dead = false;
    (async () => {
      for (let n = 1; n <= doc.numPages; n++) {
        const canvas = canvasRefs.current[n - 1];
        if (!canvas) continue;
        const page = await doc.getPage(n);
        if (dead) return;
        await page.renderCanvas(canvas);
        if (dead) return;
        const thumb = canvas.toDataURL("image/png");
        if (dead) return;
        setPages((prev) => prev.map((x) => (x.n === n ? { ...x, thumb } : x)));
      }
    })();
    return () => {
      dead = true;
    };
  }, [loading]);

  const patch = (n: number, changes: Partial<PageState>) =>
    setPages((prev) => prev.map((x) => (x.n === n ? { ...x, ...changes } : x)));

  const submit = async () => {
    const chosen = pages
      .filter((p) => p.selected)
      .map((p) => p.n)
      .sort((a, b) => a - b);
    if (chosen.length === 0) {
      setError("Chưa chọn trang nào.");
      return;
    }
    if (chosen.length > MAX_PAGES) {
      setError(`Tối đa ${MAX_PAGES} trang mỗi lần gửi.`);
      return;
    }
    setError(null);
    setBusy(true);
    const rotate: Record<string, number> = {};
    for (const p of pages) if (p.rotate !== 0) rotate[String(p.n)] = p.rotate;
    try {
      const job = await api.uploadJob(file, { preprocess: { pages: chosen, rotate } });
      toast.success("Đã tải lên — đang chờ xử lý.");
      onUploaded(job);
    } catch (err) {
      // R51: inline wizard-error kept; toast mirrors it (R59).
      setError(err instanceof ApiError ? err.detail : "Tải file thất bại.");
      toast.error(mapApiError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div data-testid="wizard-pdf" className="text-left">
      <p className="mb-2 text-sm font-medium">Chọn trang cần xử lý (tối đa {MAX_PAGES} trang)</p>
      {loading ? (
        <p data-testid="wizard-loading" className="mb-2 text-sm text-muted">
          Đang tải trang PDF…
        </p>
      ) : (
        <ul className="mb-2 max-h-64 space-y-1 overflow-y-auto">
          {pages.map((p) => (
            <li key={p.n} data-testid={`wizard-page-${p.n}`} className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={p.selected}
                onChange={(e) => patch(p.n, { selected: e.target.checked })}
                aria-label={`Chọn trang ${p.n}`}
              />
              {p.thumb && (
                <img
                  src={p.thumb}
                  alt={`Trang ${p.n}`}
                  className="h-10 rounded border border-border"
                />
              )}
              <span className="text-sm">Trang {p.n}</span>
              <select
                data-testid={`wizard-rotate-${p.n}`}
                value={p.rotate}
                onChange={(e) => patch(p.n, { rotate: Number(e.target.value) })}
                aria-label={`Xoay trang ${p.n}`}
                className="ml-auto rounded border border-border bg-surface px-1 py-0.5 text-sm"
              >
                <option value={0}>0°</option>
                <option value={90}>90°</option>
                <option value={180}>180°</option>
                <option value={270}>270°</option>
              </select>
            </li>
          ))}
        </ul>
      )}
      {/* Offscreen render targets — thumbnails render here, then swap to <img> dataURL */}
      <div className="hidden" aria-hidden>
        {pages.map((p) => (
          <canvas
            key={p.n}
            ref={(el) => {
              canvasRefs.current[p.n - 1] = el;
            }}
          />
        ))}
      </div>
      {error && (
        <div
          data-testid="wizard-error"
          className="mb-2 rounded-lg border border-error/40 bg-error/10 px-3 py-2 text-error"
        >
          {error}
        </div>
      )}
      <div className="flex items-center gap-2">
        <Button testid="wizard-submit" loading={busy} onClick={submit}>
          Gửi lên
        </Button>
        <Button testid="wizard-cancel" variant="ghost" onClick={onCancel}>
          Hủy
        </Button>
      </div>
    </div>
  );
}
