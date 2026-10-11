import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import PageSelectDialog from "../../src/components/PageSelectDialog";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("../../src/lib/pdfjs", () => ({
  loadPdf: vi.fn(async () => ({
    numPages: 3,
    getPage: vi.fn(async () => ({
      viewport: { width: 10, height: 10 },
      renderCanvas: vi.fn(async (c: HTMLCanvasElement) => {
        c.width = 10;
        c.height = 10;
      }),
    })),
  })),
}));

const entry = {
  name: "a.pdf",
  numPages: 3,
  pages: [1, 2, 3],
  blob: new Blob(["%PDF"], { type: "application/pdf" }),
};

beforeEach(() => vi.clearAllMocks());

function setup() {
  const onDone = vi.fn();
  const onCancel = vi.fn();
  render(<PageSelectDialog entry={entry} onCancel={onCancel} onDone={onDone} />);
  return { onDone, onCancel };
}

it("initial = selection cũ (tất cả trang); toggle off trang 2 → confirm trả [1,3]", async () => {
  const { onDone } = setup();
  await waitFor(() => expect(screen.getByTestId("pages-check-1")).toBeEnabled());
  expect(screen.getByTestId("pages-check-1")).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByTestId("pages-check-3")).toHaveAttribute("aria-pressed", "true");
  fireEvent.click(screen.getByTestId("pages-check-2"));
  expect(screen.getByTestId("pages-check-2")).toHaveAttribute("aria-pressed", "false");
  fireEvent.click(screen.getByTestId("pages-confirm"));
  expect(onDone).toHaveBeenCalledWith([1, 3]);
});

it("cancel → onCancel, không gọi onDone", () => {
  const { onDone, onCancel } = setup();
  fireEvent.click(screen.getByTestId("pages-cancel"));
  expect(onCancel).toHaveBeenCalled();
  expect(onDone).not.toHaveBeenCalled();
});

it("a11y: role=dialog + aria-modal + focus panel; Escape → onCancel", async () => {
  const { onCancel } = setup();
  const panel = screen.getByRole("dialog");
  expect(panel).toHaveAttribute("aria-modal", "true");
  expect(panel).toHaveFocus();
  fireEvent.keyDown(panel, { key: "Escape" });
  expect(onCancel).toHaveBeenCalled();
});
