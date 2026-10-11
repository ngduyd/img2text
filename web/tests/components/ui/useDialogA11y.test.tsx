import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { openDialogStack, releaseDialogToken, useDialogA11y } from "../../../src/components/ui/useDialogA11y";

/** Hook test trực tiếp: dialog giả lập tối thiểu (panel tabIndex=-1, đóng qua prop). */
function TestDialog({ open, onClose, label }: { open: boolean; onClose: () => void; label: string }) {
  const panelRef = useDialogA11y<HTMLDivElement>(open, onClose);
  if (!open) return null;
  return (
    <div ref={panelRef} data-testid={label} role="dialog" aria-modal="true" tabIndex={-1}>
      {label}
    </div>
  );
}

function Stacked({ onCloseA, onCloseB }: { onCloseA: () => void; onCloseB: () => void }) {
  return (
    <>
      <TestDialog open onClose={onCloseA} label="dialog-a" />
      <TestDialog open onClose={onCloseB} label="dialog-b" />
    </>
  );
}

it("Escape đóng CHỈ dialog trên cùng (stacked guard)", async () => {
  const user = userEvent.setup();
  const onCloseA = vi.fn();
  const onCloseB = vi.fn();
  render(<Stacked onCloseA={onCloseA} onCloseB={onCloseB} />);
  await user.keyboard("{Escape}");
  expect(onCloseB).toHaveBeenCalledTimes(1); // dialog B (top) đóng
  expect(onCloseA).not.toHaveBeenCalled(); // dialog A giữ nguyên
});

it("close trả focus về trigger đã mở dialog", () => {
  const onClose = vi.fn();
  // Trigger đang focus trước khi dialog mount (mô phỏng click trigger → mở dialog).
  const { getByRole } = render(<button type="button">trigger</button>);
  const trigger = getByRole("button", { name: "trigger" });
  trigger.focus();
  const { unmount } = render(<TestDialog open onClose={onClose} label="dialog-x" />);
  expect(screen.getByTestId("dialog-x")).toHaveFocus(); // focus đã bị dialog cướp
  unmount(); // cleanup: removeEventListener + prev.focus()
  expect(trigger).toHaveFocus();
});

it("double cleanup không lỗi/không nuốt entry khác (indexOf -1 guard)", () => {
  // Mô phỏng: 2 dialog đang mở trong stack, cleanup token A chạy 2 lần.
  const tokenA = Symbol("a");
  const tokenB = Symbol("b");
  openDialogStack.push(tokenA, tokenB);
  releaseDialogToken(tokenA); // lần 1: gỡ bình thường
  expect(openDialogStack).toEqual([tokenB]);
  releaseDialogToken(tokenA); // lần 2: token đã gone → guard chặn splice(-1) ăn entry cuối
  expect(openDialogStack).toEqual([tokenB]);
  openDialogStack.length = 0;
});

it("unmount khi dialog mở: gỡ listener (dispatch sau unmount không crash, không gọi onClose)", async () => {
  const onClose = vi.fn();
  const removeSpy = vi.spyOn(document, "removeEventListener");
  const { unmount } = render(<TestDialog open onClose={onClose} label="dialog-y" />);
  unmount();
  expect(removeSpy).toHaveBeenCalledWith("keydown", expect.any(Function));
  removeSpy.mockRestore();
  document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
  expect(onClose).not.toHaveBeenCalled();
});
