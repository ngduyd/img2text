import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../../src/api/client";
import ImageCropWizard from "../../../src/components/wizard/ImageCropWizard";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

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
    scale: vi.fn(),
    fillStyle: "",
    strokeStyle: "",
  },
}));

vi.mock("../../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../src/api/client")>();
  return { ...actual, api: { ...actual.api, uploadJob: vi.fn() } };
});

const file = new File(["img"], "photo.png", { type: "image/png" });

function renderWizard(onCancel = vi.fn(), onUploaded = vi.fn(), onFormatChange = vi.fn()) {
  render(
    <ImageCropWizard
      file={file}
      onCancel={onCancel}
      onUploaded={onUploaded}
      onFormatChange={onFormatChange}
    />,
  );
  return { onCancel, onUploaded, onFormatChange };
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

it("renders hidden measurement img + canvas sole surface; icon toolbar ABOVE canvas; display capped 720px", () => {
  renderWizard();
  const img = screen.getByTestId("wizard-image") as HTMLImageElement;
  expect(img).toBeInTheDocument();
  expect(img).toHaveClass("hidden"); // R51: measurement-only, hidden — canvas is the sole visible surface
  const canvas = screen.getByTestId("crop-canvas");
  // R61: toolbar row BEFORE canvas in DOM
  for (const id of ["btn-crop-rotate", "btn-crop-reset", "wizard-submit"]) {
    const btn = screen.getByTestId(id);
    expect(btn.compareDocumentPosition(canvas) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  }
  expect(screen.getByTestId("wizard-cancel")).toBeInTheDocument();
  loadImage();
  const el = screen.getByTestId("crop-canvas") as HTMLCanvasElement;
  // 800×600 natural → display scale capped at 720px wide, aspect preserved
  expect(el.width).toBe(720);
  expect(el.height).toBe(540);
  expect(ctx.drawImage).toHaveBeenCalled();
});

it("icon buttons carry title + aria-label tooltips (R61); submit shows format label", () => {
  renderWizard();
  for (const [id, title] of [
    ["btn-crop-rotate", "Xoay 90°"],
    ["btn-crop-reset", "Xóa vùng chọn"],
  ] as const) {
    expect(screen.getByTestId(id)).toHaveAttribute("title", title);
    expect(screen.getByTestId(id)).toHaveAttribute("aria-label", title);
  }
  // Format combo: submit is now a split button with the format in its label.
  expect(screen.getByTestId("wizard-submit")).toHaveTextContent("Gửi lên · Markdown");
  expect(screen.getByTestId("btn-format-toggle")).toBeInTheDocument();
});

it("pointer drag draws rect overlay in image px (display scaled 2x)", () => {
  renderWizard();
  loadImage();
  drawRect();
  // display (50,50)-(150,125) ×2 → image {x:100,y:100,w:200,h:150}
  // overlay drawn under ctx.scale(display→image ratio) — mock records image-px args
  expect(ctx.fillRect).toHaveBeenCalledWith(100, 100, 200, 150);
  expect(ctx.scale).toHaveBeenCalled();
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
  expect(opts?.output_format).toBe("md"); // Plan D4 default appended
  await waitFor(() => expect(onUploaded).toHaveBeenCalledWith({ id: 7, status: "queued" }));
  expect(toast.success).toHaveBeenCalledWith("Đã tải lên — đang chờ xử lý.");
});

it("outputFormat prop passes through to uploadJob (Plan D4)", async () => {
  render(
    <ImageCropWizard
      file={file}
      outputFormat="docx"
      onFormatChange={vi.fn()}
      onCancel={vi.fn()}
      onUploaded={vi.fn()}
    />,
  );
  vi.mocked(api.uploadJob).mockResolvedValue({ id: 7, status: "queued" });
  loadImage();
  expect(screen.getByTestId("wizard-submit")).toHaveTextContent("Gửi lên · Word");
  fireEvent.click(screen.getByTestId("wizard-submit")); // no rect → original File path
  await waitFor(() => expect(api.uploadJob).toHaveBeenCalledTimes(1));
  expect(vi.mocked(api.uploadJob).mock.calls[0][1]?.output_format).toBe("docx");
});

it("no rect (R62) → submit ORIGINAL File + full-image toast, no wizard-error", async () => {
  const { onUploaded } = renderWizard();
  vi.mocked(api.uploadJob).mockResolvedValue({ id: 7, status: "queued" });
  loadImage();
  fireEvent.click(screen.getByTestId("wizard-submit"));
  await waitFor(() => expect(api.uploadJob).toHaveBeenCalledTimes(1));
  expect(vi.mocked(api.uploadJob).mock.calls[0][0]).toBe(file);
  expect(toast.success).toHaveBeenCalledWith("Không có vùng chọn — gửi ảnh gốc");
  await waitFor(() => expect(onUploaded).toHaveBeenCalledWith({ id: 7, status: "queued" }));
  expect(screen.queryByTestId("wizard-error")).not.toBeInTheDocument();
});

it("rect smaller than 10 image-px ignored → full-image upload (R62 fallback)", async () => {
  renderWizard();
  vi.mocked(api.uploadJob).mockResolvedValue({ id: 7, status: "queued" });
  loadImage();
  const canvas = screen.getByTestId("crop-canvas");
  fireEvent.pointerDown(canvas, { clientX: 50, clientY: 50 });
  fireEvent.pointerMove(canvas, { clientX: 52, clientY: 53 }); // 4×6 image-px
  fireEvent.pointerUp(canvas, { clientX: 52, clientY: 53 });
  fireEvent.click(screen.getByTestId("wizard-submit"));
  await waitFor(() => expect(api.uploadJob).toHaveBeenCalledTimes(1));
  expect(vi.mocked(api.uploadJob).mock.calls[0][0]).toBe(file);
  expect(screen.queryByTestId("wizard-error")).not.toBeInTheDocument();
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

it("reset clears rect → submit falls back to full-image upload, no wizard-error", async () => {
  renderWizard();
  vi.mocked(api.uploadJob).mockResolvedValue({ id: 7, status: "queued" });
  loadImage();
  drawRect();
  fireEvent.click(screen.getByTestId("btn-crop-reset"));
  fireEvent.click(screen.getByTestId("wizard-submit"));
  await waitFor(() => expect(api.uploadJob).toHaveBeenCalledTimes(1));
  expect(vi.mocked(api.uploadJob).mock.calls[0][0]).toBe(file);
  expect(screen.queryByTestId("wizard-error")).not.toBeInTheDocument();
});

it("cancel calls onCancel, no api call", () => {
  const { onCancel } = renderWizard();
  fireEvent.click(screen.getByTestId("wizard-cancel"));
  expect(onCancel).toHaveBeenCalledTimes(1);
  expect(api.uploadJob).not.toHaveBeenCalled();
});
