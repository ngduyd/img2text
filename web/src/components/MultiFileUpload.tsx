import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { loadPdf } from "../lib/pdfjs";
import { MAX_PAGES, mergeToPdf } from "../hooks/useImageToPdf";
import Button from "./ui/Button";

interface Entry {
  id: number;
  kind: "image" | "pdf";
  name: string;
  blob: Blob;
  url: string;
  /** PDF: số trang gốc + trang đã chọn (1-based, mặc định tất cả). */
  numPages?: number;
  pages?: number[];
}

/** Ảnh (spec #1): jpg/png + ảnh phone heic/heif/avif — 1 file thô upload thẳng
 * (pdf-lib không embed được HEIC/AVIF → chỉ merge khi ≥2 file). */
const IMAGE_TYPES = new Set([
  "image/png",
  "image/jpeg",
  "image/heic",
  "image/heif",
  "image/avif",
]);

/**
 * Spec U1: multi-file (ảnh + PDF) với card per file, cap 25 trang, Gửi gộp → 1 PDF.
 * Crop/page-select là seam qua props — wizard cũ (lane R2) không bị đụng tới.
 */
export default function MultiFileUpload({
  onSubmit,
  beforeSubmit,
  disabled,
  onCrop,
  onSelectPages,
}: {
  /** Trả false = upload thất bại (Jobs đã toast) → GIỮ files để gửi lại. */
  onSubmit: (
    pdf: Blob,
    meta: { page_count: number; filename: string },
  ) => boolean | void | Promise<boolean | void>;
  /** Gửi → gate TRƯỚC merge (SubmitModal): false = hủy, giữ files. */
  beforeSubmit?: () => boolean | Promise<boolean>;
  /** OCR denied → chặn pick/input/Gửi. */
  disabled?: boolean;
  /** Ảnh: mở dialog crop (drag-rect) → blob đã crop. */
  onCrop?: (blob: Blob, name: string) => Promise<Blob | null>;
  /** PDF: mở dialog chọn trang → mảng trang mới (null = hủy). */
  onSelectPages?: (entry: {
    name: string;
    numPages: number;
    pages: number[];
    blob: Blob;
  }) => Promise<number[] | null>;
}) {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const idRef = useRef(0);
  // Mirror đồng bộ của entries — addFiles async cần tổng trang tươi giữa các lần await.
  const entriesRef = useRef<Entry[]>([]);
  const commit = (list: Entry[]) => {
    entriesRef.current = list;
    setEntries(list);
  };

  // Object URL theo entry — revoke khi xóa/unmount.
  const urls = useRef(new Map<number, string>());
  useEffect(() => () => [...urls.current.values()].forEach((u) => URL.revokeObjectURL(u)), []);

  const total = (list: Entry[]) =>
    list.reduce((s, e) => s + (e.kind === "image" ? 1 : e.pages?.length ?? e.numPages ?? 0), 0);

  const addFiles = async (files: FileList | File[] | null | undefined) => {
    if (!files || disabled) return;
    let running = total(entriesRef.current);
    for (const f of Array.from(files)) {
      if (IMAGE_TYPES.has(f.type)) {
        if (running + 1 > MAX_PAGES) {
          toast.error(`Tối đa ${MAX_PAGES} trang mỗi lần gửi.`);
          continue;
        }
        const id = idRef.current++;
        const url = URL.createObjectURL(f);
        urls.current.set(id, url);
        running += 1;
        commit([...entriesRef.current, { id, kind: "image", name: f.name, blob: f, url }]);
      } else if (f.type === "application/pdf") {
        try {
          const doc = await loadPdf(f);
          if (running + doc.numPages > MAX_PAGES) {
            toast.error(`Tối đa ${MAX_PAGES} trang mỗi lần gửi.`);
            continue;
          }
          const id = idRef.current++;
          running += doc.numPages;
          commit([
            ...entriesRef.current,
            {
              id,
              kind: "pdf",
              name: f.name,
              blob: f,
              url: "",
              numPages: doc.numPages,
              pages: Array.from({ length: doc.numPages }, (_, i) => i + 1),
            },
          ]);
        } catch {
          toast.error("Không đọc được file PDF.");
        }
      } else {
        toast.error("Định dạng file không được hỗ trợ.");
      }
    }
  };

  const remove = (id: number) => {
    const u = urls.current.get(id);
    if (u) {
      URL.revokeObjectURL(u);
      urls.current.delete(id);
    }
    commit(entriesRef.current.filter((e) => e.id !== id));
  };

  const crop = async (e: Entry) => {
    if (!onCrop) return;
    const out = await onCrop(e.blob, e.name);
    if (!out) return;
    // Thumbnail cũ là blob URL của blob cũ → revoke + store url mới (P2 stale crop).
    const old = urls.current.get(e.id);
    if (old) URL.revokeObjectURL(old);
    const url = URL.createObjectURL(out);
    urls.current.set(e.id, url);
    commit(entriesRef.current.map((x) => (x.id === e.id ? { ...x, blob: out, url } : x)));
  };

  const pickPages = async (e: Entry) => {
    if (!onSelectPages || e.numPages === undefined) return;
    const next = await onSelectPages({
      name: e.name,
      numPages: e.numPages,
      pages: e.pages ?? [],
      blob: e.blob,
    });
    if (!next) return;
    const filtered = next.filter((n) => n >= 1 && n <= e.numPages!);
    // Chặn deselect-all (P2): luôn ≥1 trang, giữ selection cũ.
    if (filtered.length === 0) {
      toast.error("Chọn ít nhất 1 trang.");
      return;
    }
    if (total(entriesRef.current) - (e.pages?.length ?? 0) + filtered.length > MAX_PAGES) {
      toast.error(`Tối đa ${MAX_PAGES} trang mỗi lần gửi.`);
      return;
    }
    commit(entriesRef.current.map((x) => (x.id === e.id ? { ...x, pages: filtered } : x)));
  };

  const clear = () => {
    for (const u of urls.current.values()) URL.revokeObjectURL(u);
    urls.current.clear();
    commit([]);
  };

  const submit = async () => {
    setBusy(true);
    try {
      if (beforeSubmit && !(await beforeSubmit())) return;
      // 1 ảnh → gửi nguyên file (giữ đuôi + Content-Type; server rasterize —
      // pdf-lib không embed HEIC/AVIF, và merged PDF + đuôi .png dính magic-sniff 422).
      const single = entries.length === 1 ? entries[0] : undefined;
      if (single?.kind === "image") {
        const okSingle = await onSubmit(single.blob, { page_count: 1, filename: single.name });
        if (okSingle === false) return;
        clear();
        return;
      }
      const pdf = await mergeToPdf(
        entries.map((e) => ({ kind: e.kind, blob: e.blob, name: e.name, pages: e.pages })),
      );
      // P1: 1 file → tên gốc; nhiều file → tên file đầu tiên (search theo filename sống).
      const name = entries[0]?.name?.trim() || `hop-the-${entries.length}-anh.pdf`;
      const ok = await onSubmit(pdf, { page_count: total(entries), filename: name });
      if (ok === false) return;
      clear();
    } catch (err) {
      // pdf-lib/pngjs throw raw strings ("The input is not a PNG file!") — surface luôn.
      const msg = typeof err === "string" ? err : err instanceof Error ? err.message : "";
      toast.error(msg || "Ghép PDF thất bại.");
    } finally {
      setBusy(false);
    }
  };

  const drop = (e: React.DragEvent) => {
    e.preventDefault();
    void addFiles(e.dataTransfer?.files);
  };

  return (
    <div data-testid="multi-file-upload">
      {/* Cluster cũ: [hint | Gửi] — layout khung không đổi (spec U1). */}
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted">
          {entries.length > 0 && `${entries.length} file · ${total(entries)} trang / ${MAX_PAGES}`}
        </p>
        <Button
          testid="muf-submit"
          className="ml-auto"
          disabled={disabled || entries.length === 0 || total(entries) === 0 || busy}
          loading={busy}
          onClick={() => void submit()}
        >
          Gửi
        </Button>
      </div>
      <div
        data-testid="muf-drop"
        onDragOver={(e) => e.preventDefault()}
        onDrop={drop}
        className="rounded-card border-2 border-dashed border-border bg-surface/50 p-4 text-center transition hover:border-accent/50"
      >
        <Button testid="muf-pick" disabled={disabled} onClick={() => inputRef.current?.click()}>
          Tải file lên
        </Button>
        <p className="mt-2 text-sm text-muted">Kéo thả file vào đây hoặc chọn từ máy</p>
        <input
          ref={inputRef}
          data-testid="muf-input"
          type="file"
          multiple
          accept="image/png,image/jpeg,image/heic,image/heif,image/avif,application/pdf"
          className="hidden"
          disabled={disabled}
          onChange={(e) => {
            void addFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </div>
      <ul className="mt-2 space-y-1">
        {entries.map((e, i) => (
          <li
            key={e.id}
            data-testid={`muf-card-${i}`}
            className="flex items-center gap-2 rounded-card border border-border bg-surface px-2 py-2 text-sm"
          >
            {e.kind === "image" ? (
              <img src={e.url} alt={e.name} className="h-8 w-8 rounded object-cover" />
            ) : (
              <span className="rounded-full bg-surface-2 px-1.5 py-0.5 text-xs font-medium">PDF</span>
            )}
            <div className="min-w-0 flex-1">
              <span className="block truncate">{e.name}</span>
              <span className="block text-xs text-muted">
                {e.kind === "pdf" ? `${e.pages?.length ?? 0}/${e.numPages} trang` : "1 trang"}
              </span>
            </div>
            {e.kind === "image" && onCrop && (
              <Button testid={`muf-crop-${i}`} size="sm" variant="secondary" onClick={() => void crop(e)}>
                Chọn vùng
              </Button>
            )}
            {e.kind === "pdf" && onSelectPages && (
              <Button
                testid={`muf-pages-${i}`}
                size="sm"
                variant="secondary"
                onClick={() => void pickPages(e)}
              >
                Chọn số trang
              </Button>
            )}
            <Button testid={`muf-remove-${i}`} size="sm" variant="danger" onClick={() => remove(e.id)}>
              Xóa
            </Button>
          </li>
        ))}
      </ul>
    </div>
  );
}
