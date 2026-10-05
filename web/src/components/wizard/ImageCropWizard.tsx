import { Eraser, RotateCw, Send } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { ApiError, api } from "../../api/client";
import { mapApiError } from "../../lib/errors";
import Button from "../ui/Button";

interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Rects below this (image px) are ignored — accidental micro-drags. */
const MIN_RECT = 10;

/** Canvas display scale cap — larger bitmaps draw downscaled; rect coords stay image px. */
const MAX_DISPLAY = 720;

/** Icon-button tap target (Tailwind spacing: 10 = 2.5rem = 40px). */
const ICON_BTN = "min-h-10 min-w-10 px-2";

/** Crop wizard: draw a rect on the image, rotate 90° cw, upload the cropped JPEG. */
export default function ImageCropWizard({
  file,
  onCancel,
  onUploaded,
}: {
  file: File;
  onCancel: () => void;
  onUploaded: (job: { id: number; status: string }) => void;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [dims, setDims] = useState<{ w: number; h: number } | null>(null);
  // Rect lives in the ROTATED frame — final crop computed on the rotated bitmap.
  const [view, setView] = useState<{ rotation: number; rect: Rect | null }>({
    rotation: 0,
    rect: null,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const dragRef = useRef<{ sx: number; sy: number } | null>(null);

  useEffect(() => {
    const u = URL.createObjectURL(file);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [file]);

  const rotated = view.rotation === 90 || view.rotation === 270;
  const frameW = dims ? (rotated ? dims.h : dims.w) : 0;
  const frameH = dims ? (rotated ? dims.w : dims.h) : 0;

  // Redraw: image rotated to view.rotation + semi-transparent rect overlay (image-px coords).
  useEffect(() => {
    const canvas = canvasRef.current;
    const img = imgRef.current;
    if (!canvas || !img || !dims || !dims.w || !dims.h) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return; // jsdom without canvas package
    // Display scale: cap the long edge at MAX_DISPLAY px; pixel coords stay in image px
    // via ctx.scale below (one coordinate space for pointer math + crop).
    const scale = Math.min(1, MAX_DISPLAY / frameW);
    canvas.width = Math.round(frameW * scale);
    canvas.height = Math.round(frameH * scale);
    ctx.save();
    ctx.scale(scale, scale);
    ctx.translate(frameW / 2, frameH / 2);
    ctx.rotate((view.rotation * Math.PI) / 180);
    ctx.drawImage(img, -dims.w / 2, -dims.h / 2);
    ctx.restore();
    if (view.rect) {
      ctx.save();
      ctx.scale(scale, scale);
      ctx.fillStyle = "rgba(220, 38, 38, 0.3)";
      ctx.fillRect(view.rect.x, view.rect.y, view.rect.w, view.rect.h);
      ctx.strokeStyle = "rgba(220, 38, 38, 0.9)";
      ctx.strokeRect(view.rect.x, view.rect.y, view.rect.w, view.rect.h);
      ctx.restore();
    }
  }, [dims, frameW, frameH, view]);

  // Client px → image px in the current rotated frame (independent of canvas display scale).
  const toFrameCoords = (clientX: number, clientY: number) => {
    const canvas = canvasRef.current;
    if (!canvas || !frameW || !frameH) return null;
    const display = canvas.getBoundingClientRect();
    if (!display.width || !display.height) return null;
    return {
      x: ((clientX - display.left) / display.width) * frameW,
      y: ((clientY - display.top) / display.height) * frameH,
    };
  };

  return (
    <div data-testid="wizard-crop" className="text-left">
      <p className="mb-2 text-sm font-medium">Chọn vùng cần cắt</p>
      {/* R61: toolbar ABOVE canvas */}
      <div className="mb-2 flex items-center gap-2">
        <Button
          testid="btn-crop-rotate"
          variant="ghost"
          className={ICON_BTN}
          title="Xoay 90°"
          aria-label="Xoay 90°"
          onClick={() =>
            setView((v) => {
              if (!dims) return { ...v, rotation: (v.rotation + 90) % 360 };
              // Rect is in the current rotated frame — reproject into the next 90° cw frame.
              const curH = v.rotation === 90 || v.rotation === 270 ? dims.w : dims.h;
              const rect = v.rect
                ? { x: curH - v.rect.y - v.rect.h, y: v.rect.x, w: v.rect.h, h: v.rect.w }
                : v.rect;
              return { rotation: (v.rotation + 90) % 360, rect };
            })
          }
        >
          <RotateCw size={18} aria-hidden="true" />
        </Button>
        <Button
          testid="btn-crop-reset"
          variant="ghost"
          className={ICON_BTN}
          title="Xóa vùng chọn"
          aria-label="Xóa vùng chọn"
          onClick={() => setView((v) => ({ ...v, rect: null }))}
        >
          <Eraser size={18} aria-hidden="true" />
        </Button>
        <Button
          testid="wizard-submit"
          loading={busy}
          className={ICON_BTN}
          title="Gửi lên"
          aria-label="Gửi lên"
          onClick={async () => {
            if (!view.rect || !dims || !imgRef.current) {
              // R62: no rect → submit the ORIGINAL File untouched; no crop, no error.
              setBusy(true);
              try {
                const job = await api.uploadJob(file);
                toast.success("Không có vùng chọn — gửi ảnh gốc");
                onUploaded(job);
              } catch (err) {
                setError(err instanceof ApiError ? err.detail : "Không tải được ảnh.");
                toast.error(mapApiError(err));
              } finally {
                setBusy(false);
              }
              return;
            }
            setError(null);
            setBusy(true);
            try {
              const rect = view.rect;
              const img = imgRef.current;
              // Crop on the ROTATED bitmap: one canvas, transform then drawImage.
              const out = document.createElement("canvas");
              out.width = rect.w;
              out.height = rect.h;
              const ctx = out.getContext("2d");
              if (!ctx) throw new Error("canvas unavailable");
              ctx.save();
              ctx.translate(-rect.x, -rect.y);
              ctx.translate(frameW / 2, frameH / 2);
              ctx.rotate((view.rotation * Math.PI) / 180);
              ctx.drawImage(img, -dims.w / 2, -dims.h / 2);
              ctx.restore();
              const blob = await new Promise<Blob | null>((res) =>
                out.toBlob(res, "image/jpeg", 0.92),
              );
              if (!blob) throw new Error("toBlob failed");
              const base = file.name.replace(/\.[^.]+$/, "") || "image";
              const job = await api.uploadJob(blob, { filename: `${base}-crop.jpg` });
              toast.success("Đã tải lên — đang chờ xử lý.");
              onUploaded(job);
            } catch (err) {
              // R51: inline wizard-error kept; toast mirrors it (R59).
              setError(err instanceof ApiError ? err.detail : "Không cắt được ảnh.");
              toast.error(mapApiError(err));
            } finally {
              setBusy(false);
            }
          }}
        >
          <Send size={18} aria-hidden="true" />
        </Button>
      </div>
      {/* R51: measurement-only — hidden; canvas is the sole visible surface */}
      <img
        ref={imgRef}
        data-testid="wizard-image"
        src={url ?? undefined}
        alt="Ảnh cần cắt"
        className="hidden"
        onLoad={() => {
          const img = imgRef.current;
          if (img) setDims({ w: img.naturalWidth, h: img.naturalHeight });
        }}
      />
      <canvas
        ref={canvasRef}
        data-testid="crop-canvas"
        className="max-w-full touch-none"
        onPointerDown={(e) => {
          if (!dims) return;
          const p = toFrameCoords(e.clientX, e.clientY);
          if (!p) return;
          dragRef.current = { sx: p.x, sy: p.y };
          setView((v) => ({ ...v, rect: null }));
        }}
        onPointerMove={(e) => {
          const drag = dragRef.current;
          if (!drag || !dims) return;
          const p = toFrameCoords(e.clientX, e.clientY);
          if (!p) return;
          const x = Math.min(drag.sx, p.x);
          const y = Math.min(drag.sy, p.y);
          const w = Math.abs(p.x - drag.sx);
          const h = Math.abs(p.y - drag.sy);
          const rect = w >= MIN_RECT && h >= MIN_RECT ? { x, y, w, h } : null;
          setView((v) => ({ ...v, rect }));
        }}
        onPointerUp={() => {
          dragRef.current = null;
        }}
      />
      {error && (
        <div
          data-testid="wizard-error"
          className="mb-2 rounded-lg border border-error/40 bg-error/10 px-3 py-2 text-error"
        >
          {error}
        </div>
      )}
      <div className="mt-2 flex items-center gap-2">
        <Button testid="wizard-cancel" variant="ghost" onClick={onCancel}>
          Hủy
        </Button>
      </div>
    </div>
  );
}
