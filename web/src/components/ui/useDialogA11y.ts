import { useEffect, useRef } from "react";

/**
 * a11y dialog dùng chung (CropDialog/PageSelectDialog/SubmitModal):
 * - focus vào panel khi mở (panel nhận tabIndex={-1}),
 * - Escape → onClose CHỈ khi dialog trên cùng stack (đồng thời mở 2 dialog → đóng 1),
 * - trả focus về element đã mở dialog khi đóng (best-effort: trigger có thể unmount).
 * role/aria-modal/aria-labelledby gắn JSX riêng theo id heading từng dialog.
 */

/** Stack các dialog đang mở — dialog cuối = trên cùng, chỉ nó nhận Escape.
 *  Export cho test double-cleanup guard. */
export const openDialogStack: symbol[] = [];

/** Gỡ token có guard: cleanup có thể chạy lần 2 (indexOf = -1) → KHÔNG được splice entry cuối. */
export function releaseDialogToken(token: symbol) {
  const i = openDialogStack.indexOf(token);
  if (i >= 0) openDialogStack.splice(i, 1);
}

export function useDialogA11y<T extends HTMLElement>(open: boolean, onClose: () => void) {
  const panelRef = useRef<T>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    panelRef.current?.focus();
    const token = Symbol("dialog");
    openDialogStack.push(token);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && openDialogStack[openDialogStack.length - 1] === token) closeRef.current();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      releaseDialogToken(token);
      prev?.focus();
    };
  }, [open]);

  return panelRef;
}
