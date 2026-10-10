import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import CropDialog from "../../src/components/CropDialog";

// jsdom canvas: getContext returns null unless mocked — recording 2d ctx.
const { ctx } = vi.hoisted(() => ({
  ctx: {
    drawImage: vi.fn(),
    fillRect: vi.fn(),
    strokeRect: vi.fn(),
    save: vi.fn(),
    restore: vi.fn(),
    scale: vi.fn(),
    fillStyle: "",
    strokeStyle: "",
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
  Object.defineProperty(URL, "createObjectURL", {
    value: vi.fn(() => "blob:mock"),
    configurable: true,
    writable: true,
  });
  Object.defineProperty(URL, "revokeObjectURL", { value: vi.fn(), configurable: true, writable: true });
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
    ctx as unknown as CanvasRenderingContext2D,
  );
  vi.spyOn(HTMLCanvasElement.prototype, "getBoundingClientRect").mockReturnValue({
    x: 0, y: 0, left: 0, top: 0, right: 400, bottom: 300, width: 400, height: 300,
    toJSON: () => ({}),
  } as DOMRect);
  vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation((cb) => {
    cb(new Blob([new Uint8Array([1, 2, 3])], { type: "image/jpeg" }));
  });
});

const blob = new Blob(["img"], { type: "image/png" });

function setup() {
  const onDone = vi.fn();
  const onCancel = vi.fn();
  render(<CropDialog blob={blob} name="photo.png" onCancel={onCancel} onDone={onDone} />);
  // jsdom imgs never load — set natural dims then fire load.
  const img = screen.getByTestId("crop-image") as HTMLImageElement;
  Object.defineProperty(img, "naturalWidth", { value: 800, configurable: true });
  Object.defineProperty(img, "naturalHeight", { value: 600, configurable: true });
  fireEvent.load(img);
  return { onDone, onCancel };
}

it("drag-rect: display 400×300 vs image 800×600 → overlay image px", () => {
  setup();
  const canvas = screen.getByTestId("crop-canvas");
  fireEvent.pointerDown(canvas, { clientX: 50, clientY: 50 });
  fireEvent.pointerMove(canvas, { clientX: 150, clientY: 125 });
  fireEvent.pointerUp(canvas, { clientX: 150, clientY: 125 });
  expect(ctx.fillRect).toHaveBeenCalledWith(100, 100, 200, 150);
});

it("confirm with rect → onDone(cropped JPEG)", async () => {
  const { onDone } = setup();
  const canvas = screen.getByTestId("crop-canvas");
  fireEvent.pointerDown(canvas, { clientX: 50, clientY: 50 });
  fireEvent.pointerMove(canvas, { clientX: 150, clientY: 125 });
  fireEvent.pointerUp(canvas, { clientX: 150, clientY: 125 });
  fireEvent.click(screen.getByTestId("crop-confirm"));
  await waitFor(() => expect(onDone).toHaveBeenCalled());
  expect(onDone.mock.calls[0][0]).toBeInstanceOf(Blob);
  expect(onDone.mock.calls[0][0].type).toBe("image/jpeg");
});

it("no rect → onDone(original blob); cancel → onCancel", async () => {
  const { onDone, onCancel } = setup();
  fireEvent.click(screen.getByTestId("crop-confirm"));
  await waitFor(() => expect(onDone).toHaveBeenCalledWith(blob));
  fireEvent.click(screen.getByTestId("crop-cancel"));
  expect(onCancel).toHaveBeenCalled();
});
