import { useCallback, useRef, useState } from "react";
import type { ReactNode } from "react";

/**
 * Chia vùng xem 2 pane kiểu cửa sổ Windows: kéo thanh giữa để đổi tỉ lệ.
 * Pointer events (chuột + cảm ứng cùng một đường), tỉ lệ lưu vào localStorage.
 *
 * `first` = null → chỉ render `second` (nhưng VẪN giữ nguyên vị trí cây React để
 * pane thứ hai không bị remount khi bật/tắt ảnh gốc — remount sẽ chạy lại
 * export/preview và mất nội dung đang sửa).
 */
export default function SplitPane({
  axis,
  storageKey,
  first,
  second,
  min = 15,
  heightClass = "h-full",
}: {
  axis: "x" | "y";
  storageKey: string;
  first: ReactNode | null;
  second: ReactNode;
  /** % tối thiểu mỗi pane. */
  min?: number;
  heightClass?: string;
}) {
  const [pct, setPct] = useState<number>(() => {
    const saved = typeof localStorage === "undefined" ? null : localStorage.getItem(storageKey);
    const n = Number(saved);
    return Number.isFinite(n) && n >= min && n <= 100 - min ? n : 50;
  });
  const wrapRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  const active = first !== null;

  const apply = useCallback(
    (clientX: number, clientY: number) => {
      const box = wrapRef.current?.getBoundingClientRect();
      if (!box) return;
      const raw = axis === "x" ? (clientX - box.left) / box.width : (clientY - box.top) / box.height;
      const next = Math.min(100 - min, Math.max(min, Math.round(raw * 100)));
      setPct(next);
    },
    [axis, min],
  );

  const persist = (value: number) => {
    try {
      localStorage.setItem(storageKey, String(value));
    } catch {
      // localStorage bị chặn → chỉ mất tỉ lệ ở lần mở sau.
    }
  };

  return (
    <div
      ref={wrapRef}
      data-testid={active ? `split-pane-${axis}` : "split-pane-empty"}
      /* Không chia thì KHÔNG khoá chiều cao: editor tự cao theo nội dung (khoá sẽ
         làm panel tràn khỏi khung → footer đè lên hàng Save ở mobile). */
      className={`flex min-h-0 min-w-0 ${active ? heightClass : ""} ${axis === "x" ? "flex-row" : "flex-col"}`}
    >
      {active && (
        <>
          <div style={{ flexBasis: `${pct}%` }} className="min-h-0 min-w-0 overflow-auto">
            {first}
          </div>
          <div
            data-testid={`split-handle-${axis}`}
            role="separator"
            aria-orientation={axis === "x" ? "vertical" : "horizontal"}
            aria-valuenow={pct}
            aria-valuemin={min}
            aria-valuemax={100 - min}
            tabIndex={0}
            className={`shrink-0 bg-border transition-colors duration-150 ease-out hover:bg-accent focus-visible:bg-accent ${
              axis === "x" ? "w-1.5 cursor-col-resize" : "h-1.5 cursor-row-resize"
            }`}
            onPointerDown={(e) => {
              dragging.current = true;
              e.currentTarget.setPointerCapture(e.pointerId);
            }}
            onPointerMove={(e) => {
              if (dragging.current) apply(e.clientX, e.clientY);
            }}
            onPointerUp={() => {
              dragging.current = false;
              persist(pct);
            }}
            onPointerCancel={() => {
              dragging.current = false;
              persist(pct);
            }}
            onKeyDown={(e) => {
              const back = axis === "x" ? e.key === "ArrowLeft" : e.key === "ArrowUp";
              const fwd = axis === "x" ? e.key === "ArrowRight" : e.key === "ArrowDown";
              if (!back && !fwd) return;
              e.preventDefault();
              const next = Math.min(100 - min, Math.max(min, pct + (fwd ? 5 : -5)));
              setPct(next);
              persist(next);
            }}
          />
        </>
      )}
      <div
        style={active ? { flexBasis: `${100 - pct}%` } : undefined}
        className={`min-h-0 min-w-0 ${active ? "overflow-auto" : "flex-1"}`}
      >
        {second}
      </div>
    </div>
  );
}
