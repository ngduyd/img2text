import Button from "./ui/Button";
import { useT } from "../i18n";
import { useDialogA11y } from "./ui/useDialogA11y";

/**
 * Spec #1: confirm dialog destructive dùng chung (JobRow overflow + JobDetail).
 * useDialogA11y: focus panel, Escape đóng (trên cùng stack), trả focus về trigger.
 */
export default function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  message: string;
  /** Omitted → dict common.delete. */
  confirmLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const { t } = useT();
  const panelRef = useDialogA11y<HTMLDivElement>(open, onCancel);
  if (!open) return null;
  return (
    <div
      data-testid="confirm-dialog"
      className="fixed inset-0 z-50 flex items-center justify-center bg-overlay p-4"
    >
      <div
        ref={panelRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        aria-describedby="confirm-dialog-message"
        tabIndex={-1}
        className="w-full max-w-sm rounded-card border border-border bg-surface p-4 text-left outline-none"
      >
        <h2 id="confirm-dialog-title" className="text-base font-semibold text-text">
          {title}
        </h2>
        <p id="confirm-dialog-message" className="mt-2 text-sm text-muted">
          {message}
        </p>
        <div className="mt-4 flex justify-end gap-2">
          <Button testid="confirm-cancel" variant="secondary" size="sm" onClick={onCancel}>
            {t("common.cancel")}
          </Button>
          <Button testid="confirm-accept" variant="danger" size="sm" onClick={onConfirm}>
            {confirmLabel ?? t("common.delete")}
          </Button>
        </div>
      </div>
    </div>
  );
}
