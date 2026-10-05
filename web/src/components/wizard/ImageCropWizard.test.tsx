import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../api/client";
import ImageCropWizard from "./ImageCropWizard";

// jsdom canvas: getContext returns null unless mocked — recording 2d ctx.
const { ctx } = vi.hoisted(() => ({
  ctx: {
    drawImage: vi.fn(),
    fillRect: vi.fn(),
    strokeRect: vi.fn(),
    save: vi.fn(),
    restore: vi.fn(),
    translate: vi.fn(),
    rotate: vi.fn(),
    fillStyle: "",
    strokeStyle: "",
  },
}));

vi.mock("../../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/client")>();
  return { ...actual, api: { ...actual.api, uploadJob: vi.fn() } };
});

const file = new File(["img"], "photo.png", { type: "image/png" });

function renderWizard(onCancel = vi.fn(), onUploaded = vi.fn()) {
  render(<ImageCropWizard file={file} onCancel={onCancel} onUploaded={onUploaded} />);
  return { onCancel, onUploaded };
}

/** jsdom imgs never load — set natural dims then fire load. */
function loadImage(w = 800, h = 600) {
  const img = screen.getByTestId("wizard-image") as HTMLImageElement;
  Object.defineProperty(img, "naturalWidth", { value: w, configurable: true });
  Object.defineProperty(img, "naturalHeight", { value: h, configurable: true });
  fireEvent.load(img);
}

/** Display 400×300 vs canvas 800×600 → scale 2 (display→image px). */
function drawRect() {
  const canvas = screen.getByTestId("crop-canvas");
  fireEvent.pointerDown(canvas, { clientX: 50, clientY: 50 });
  fireEvent.pointerMove(canvas, { clientX: 150, clientY: 125 });
  fireEvent.pointerUp(canvas, { clientX: 150, clientY: 125 });
}

beforeEach(() => {
  vi.clearAllMocks();
  // jsdom has no URL.createObjectURL — stub object URL for <img src>.
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
    x: 0,
    y: 0,
    left: 0,
    top: 0,
    right: 400,
    bottom: 300,
    width: 400,
    height: 300,
    toJSON: () => ({}),
  } as DOMRect);
  // toBlob is async callback — jsdom not implemented; mock delivers JPEG bytes.
  vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation((cb) => {
    act(() => cb(new Blob([new Uint8Array([1, 2, 3, 84, 71, 70])], { type: "image/jpeg" })));
  });
});

it("renders wizard-image + crop-canvas + crop buttons; canvas at natural dims on load", () => {
  renderWizard();
  expect(screen.getByTestId("wizard-image")).toBeInTheDocument();
  expect(screen.getByTestId("crop-canvas")).toBeInTheDocument();
  for (const id of ["btn-crop-rotate", "btn-crop-reset", "wizard-submit", "wizard-cancel"]) {
    expect(screen.getByTestId(id)).toBeInTheDocument();
  }
  loadImage();
  const canvas = screen.getByTestId("crop-canvas") as HTMLCanvasElement;
  expect(canvas.width).toBe(800);
  expect(canvas.height).toBe(600);
  expect(ctx.drawImage).toHaveBeenCalled();
});

it("pointer drag draws rect overlay in image px (display scaled 2x)", () => {
  renderWizard();
  loadImage();
  drawRect();
  // display (50,50)-(150,125) ×2 → image {x:100,y:100,w:200,h:150}
  expect(ctx.fillRect).toHaveBeenCalledWith(100, 100, 200, 150);
  expect(String(ctx.fillStyle)).toContain("rgba");
});

it("submit uploads cropped JPEG blob with -crop.jpg filename, NOT the original File", async () => {
  const { onUploaded } = renderWizard();
  vi.mocked(api.uploadJob).mockResolvedValue({ id: 7, status: "queued" });
  loadImage();
  drawRect();
  fireEvent.click(screen.getByTestId("wizard-submit"));
  await waitFor(() => expect(api.uploadJob).toHaveBeenCalledTimes(1));
  const [blob, opts] = vi.mocked(api.uploadJob).mock.calls[0];
  expect(blob).toBeInstanceOf(Blob);
  expect(blob).not.toBeInstanceOf(File);
  expect(blob).not.toBe(file);
  expect(blob.type).toBe("image/jpeg");
  expect(blob.size).toBeGreaterThan(0);
  expect(opts?.filename).toBe("photo-crop.jpg");
  await waitFor(() => expect(onUploaded).toHaveBeenCalledWith({ id: 7, status: "queued" }));
});

it("no rect → wizard-error 'Chọn vùng cần cắt trước.', NO api call", async () => {
  renderWizard();
  loadImage();
  fireEvent.click(screen.getByTestId("wizard-submit"));
  expect(await screen.findByTestId("wizard-error")).toHaveTextContent("Chọn vùng cần cắt trước.");
  expect(api.uploadJob).not.toHaveBeenCalled();
});

it("rect smaller than 10 image-px is ignored", async () => {
  renderWizard();
  loadImage();
  const canvas = screen.getByTestId("crop-canvas");
  fireEvent.pointerDown(canvas, { clientX: 50, clientY: 50 });
  fireEvent.pointerMove(canvas, { clientX: 52, clientY: 53 }); // 4×6 image-px
  fireEvent.pointerUp(canvas, { clientX: 52, clientY: 53 });
  fireEvent.click(screen.getByTestId("wizard-submit"));
  expect(await screen.findByTestId("wizard-error")).toHaveTextContent("Chọn vùng cần cắt trước.");
  expect(api.uploadJob).not.toHaveBeenCalled();
});

it("rotate 90° cw twice → ctx.save/rotate/restore sequence recorded", async () => {
  renderWizard();
  loadImage();
  fireEvent.click(screen.getByTestId("btn-crop-rotate"));
  fireEvent.click(screen.getByTestId("btn-crop-rotate"));
  await waitFor(() => expect(ctx.rotate).toHaveBeenCalledWith(Math.PI / 2));
  expect(ctx.rotate).toHaveBeenCalledWith(Math.PI);
  expect(ctx.save).toHaveBeenCalled();
  expect(ctx.restore).toHaveBeenCalled();
});

it("rotate reprojects existing rect into the rotated frame (crop on ROTATED bitmap)", () => {
  renderWizard();
  loadImage();
  drawRect(); // {100,100,200,150} in 800×600 frame
  fireEvent.click(screen.getByTestId("btn-crop-rotate"));
  // 90° cw: {x: curH-y-h, y: x, w: h, h: w} = {350,100,150,200} in 600×800 frame
  expect(ctx.fillRect).toHaveBeenCalledWith(350, 100, 150, 200);
});

it("reset clears rect → submit errors, no api call", async () => {
  renderWizard();
  loadImage();
  drawRect();
  fireEvent.click(screen.getByTestId("btn-crop-reset"));
  fireEvent.click(screen.getByTestId("wizard-submit"));
  expect(await screen.findByTestId("wizard-error")).toHaveTextContent("Chọn vùng cần cắt trước.");
  expect(api.uploadJob).not.toHaveBeenCalled();
});

it("cancel calls onCancel, no api call", () => {
  const { onCancel } = renderWizard();
  fireEvent.click(screen.getByTestId("wizard-cancel"));
  expect(onCancel).toHaveBeenCalledTimes(1);
  expect(api.uploadJob).not.toHaveBeenCalled();
});
