import { useEffect, useRef } from "react";

/**
 * a11y dialog dùng chung (CropDialog/PageSelectDialog/SubmitModal):
 * - focus vào panel khi mở (panel nhận tabIndex={-1}),
 * - Escape → onClose (document listener — không cần focus đúng trigger),
 * - trả focus về element đã mở dialog khi đóng (best-effort: trigger có thể unmount).
 * role/aria-modal/aria-labelledby gắn JSX riêng theo id heading từng dialog.
 */
export function useDialogA11y<T extends HTMLElement>(open: boolean, onClose: () => void) {
  const panelRef = useRef<T>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    panelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeRef.current();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      prev?.focus();
    };
  }, [open]);

  return panelRef;
}
