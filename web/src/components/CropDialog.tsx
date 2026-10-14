import { useEffect, useRef, useState } from "react";
import { useT } from "../i18n";
import Button from "./ui/Button";
import { useDialogA11y } from "./ui/useDialogA11y";

/** Rects below this (image px) are ignored — accidental micro-drags. */
const MIN_RECT = 10;

/** Canvas display scale cap — larger bitmaps draw downscaled; rect coords are image px. */
const MAX_DISPLAY = 720;

interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Crop-rect overlay from the --error token (theme-aware; ui-ux-dev: no hardcoded colors).
 * ponytail: fallback rgba only if the token is missing — canvas can't read CSS vars directly. */
function errorOverlay(): { fill: string; stroke: string } {
  const hex = getComputedStyle(document.documentElement)
    .getPropertyValue("--error")
    .trim()
    .replace("#", "");
  if (!/^[0-9a-f]{6}$/i.test(hex)) return { fill: "rgba(248,81,73,0.3)", stroke: "rgba(248,81,73,0.9)" };
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16));
  return { fill: `rgba(${r},${g},${b},0.3)`, stroke: `rgba(${r},${g},${b},0.9)` };
}

/**
 * Spec U4: crop per-image trong multi-file flow — drag-rect trên canvas → JPEG blob.
 * Đơn giản hơn ImageCropWizard cũ (bỏ rotate/submit upload): dialog chỉ trả blob.
 * ponytail: no-rect → trả blob gốc (giống R62); thêm rotate nếu user hỏi.
 * ponytail: keyboard rect editing (arrow-nudge) deferred — drag + nút chọn toàn bộ ảnh đủ.
 */
export default function CropDialog({
  blob,
  name,
  onCancel,
  onDone,
}: {
  blob: Blob;
  name: string;
  onCancel: () => void;
  onDone: (blob: Blob) => void;
}) {
  const { t } = useT();
  const [url, setUrl] = useState<string | null>(null);
  const [dims, setDims] = useState<{ w: number; h: number } | null>(null);
  const [rect, setRect] = useState<Rect | null>(null);
  const imgRef = useRef<HTMLImageElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const dragRef = useRef<{ sx: number; sy: number } | null>(null);
  const panelRef = useDialogA11y<HTMLDivElement>(true, onCancel);

  useEffect(() => {
    const u = URL.createObjectURL(blob);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [blob]);

  // Redraw: image downscaled to display + semi-transparent rect overlay (image px).
  useEffect(() => {
    const canvas = canvasRef.current;
    const img = imgRef.current;
    if (!canvas || !img || !dims) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return; // jsdom without canvas package
    const scale = Math.min(1, MAX_DISPLAY / dims.w);
    canvas.width = Math.round(dims.w * scale);
    canvas.height = Math.round(dims.h * scale);
    ctx.save();
    ctx.scale(scale, scale);
    ctx.drawImage(img, 0, 0);
    if (rect) {
      const overlay = errorOverlay();
      ctx.fillStyle = overlay.fill;
      ctx.fillRect(rect.x, rect.y, rect.w, rect.h);
      ctx.strokeStyle = overlay.stroke;
      ctx.strokeRect(rect.x, rect.y, rect.w, rect.h);
    }
    ctx.restore();
  }, [dims, rect]);

  // Client px → image px (canvas display is scaled; one coordinate space = image px).
  const toImageCoords = (clientX: number, clientY: number) => {
    const canvas = canvasRef.current;
    if (!canvas || !dims) return null;
    const display = canvas.getBoundingClientRect();
    if (!display.width || !display.height) return null;
    return {
      x: ((clientX - display.left) / display.width) * dims.w,
      y: ((clientY - display.top) / display.height) * dims.h,
    };
  };

  const confirm = async () => {
    // No rect → original blob untouched (R62).
    const img = imgRef.current;
    if (!rect || !dims || !img) {
      onDone(blob);
      return;
    }
    const out = document.createElement("canvas");
    out.width = Math.round(rect.w);
    out.height = Math.round(rect.h);
    const ctx = out.getContext("2d");
    if (!ctx) {
      onDone(blob);
      return;
    }
    ctx.drawImage(img, rect.x, rect.y, rect.w, rect.h, 0, 0, out.width, out.height);
    const cropped = await new Promise<Blob | null>((res) => out.toBlob(res, "image/jpeg", 0.92));
    onDone(cropped ?? blob);
  };

  return (
    <div
      data-testid="crop-dialog"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="crop-dialog-title"
        tabIndex={-1}
        className="w-full max-w-lg rounded-card border border-border bg-surface p-4 text-left outline-none"
      >
        <p id="crop-dialog-title" className="mb-2 text-sm font-medium">
          {t("upload.cropTitle", { name })}
        </p>
        {/* Measurement-only — canvas is the sole visible surface. */}
        <img
          ref={imgRef}
          data-testid="crop-image"
          src={url ?? undefined}
          alt={name}
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
            const p = toImageCoords(e.clientX, e.clientY);
            if (!p) return;
            dragRef.current = { sx: p.x, sy: p.y };
            setRect(null);
          }}
          onPointerMove={(e) => {
            const drag = dragRef.current;
            if (!drag) return;
            const p = toImageCoords(e.clientX, e.clientY);
            if (!p) return;
            const x = Math.min(drag.sx, p.x);
            const y = Math.min(drag.sy, p.y);
            const w = Math.abs(p.x - drag.sx);
            const h = Math.abs(p.y - drag.sy);
            setRect(w >= MIN_RECT && h >= MIN_RECT ? { x, y, w, h } : null);
          }}
          onPointerUp={() => {
            dragRef.current = null;
          }}
        />
        <div className="mt-3 flex items-center justify-end gap-2">
          <Button
            testid="btn-crop-full"
            variant="ghost"
            size="sm"
            className="mr-auto"
            disabled={!dims}
            onClick={() => dims && setRect({ x: 0, y: 0, w: dims.w, h: dims.h })}
          >
            {t("upload.cropFull")}
          </Button>
          <Button testid="crop-cancel" variant="ghost" onClick={onCancel}>
            {t("common.cancel")}
          </Button>
          <Button testid="crop-confirm" onClick={() => void confirm()}>
            {t("upload.cropConfirm")}
          </Button>
        </div>
      </div>
    </div>
  );
}
