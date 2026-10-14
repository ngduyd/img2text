import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import SubmitModal from "../../src/components/SubmitModal";

function setup() {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  render(<SubmitModal open onConfirm={onConfirm} onCancel={onCancel} />);
  return { onConfirm, onCancel };
}

it("extract_only → callback mode=extract_only, output_format=md", () => {
  const { onConfirm } = setup();
  fireEvent.click(screen.getByTestId("sm-mode-extract-only"));
  fireEvent.click(screen.getByTestId("sm-confirm"));
  expect(onConfirm).toHaveBeenCalledWith({ mode: "extract_only", output_format: "md" });
});

it("layout + word → callback mode=layout, output_format=docx", () => {
  const { onConfirm } = setup();
  fireEvent.click(screen.getByTestId("sm-format-docx"));
  fireEvent.click(screen.getByTestId("sm-confirm"));
  expect(onConfirm).toHaveBeenCalledWith({ mode: "layout", output_format: "docx" });
});

it("extract_only ẩn radio md/word; Hủy → onCancel", () => {
  const { onConfirm, onCancel } = setup();
  fireEvent.click(screen.getByTestId("sm-mode-extract-only"));
  expect(screen.queryByTestId("sm-format-md")).toBeNull();
  expect(onConfirm).not.toHaveBeenCalled();
  fireEvent.click(screen.getByTestId("sm-cancel"));
  expect(onCancel).toHaveBeenCalled();
});

it("open=false → không render", () => {
  render(<SubmitModal open={false} onConfirm={vi.fn()} onCancel={vi.fn()} />);
  expect(screen.queryByTestId("submit-modal")).toBeNull();
});

it("a11y: role=dialog + aria-modal + focus panel; Escape → onCancel", () => {
  const { onCancel } = setup();
  const panel = screen.getByRole("dialog");
  expect(panel).toHaveAttribute("aria-modal", "true");
  expect(panel).toHaveFocus();
  fireEvent.keyDown(panel, { key: "Escape" });
  expect(onCancel).toHaveBeenCalled();
});

/** P2: 2 fieldset đều có legend là child đầu tiên → group accessible name (SR associate qua legend). */
it("a11y: cả 2 fieldset đều có accessible name từ legend", () => {
  setup();
  expect(screen.getByRole("group", { name: "Processing mode" })).toBeInTheDocument();
  expect(screen.getByRole("group", { name: "Format" })).toBeInTheDocument();
});
