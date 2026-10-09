import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createEvent, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { toast } from "sonner";
import { api } from "../../src/api/client";
import type { User } from "../../src/api/types";
import Dropzone from "../../src/components/Dropzone";
import { loadPdf } from "../../src/lib/pdfjs";

// R30: pdfjs mocked at module boundary — pdf wizard never loads real pdfjs in tests.
vi.mock("../../src/lib/pdfjs", () => ({
  loadPdf: vi.fn(async () => ({
    numPages: 1,
    getPage: vi.fn(async () => ({ viewport: { width: 10, height: 10 }, renderCanvas: vi.fn() })),
  })),
}));

vi.mock("../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
      uploadJob: vi.fn(),
    },
  };
});

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function renderDropzone(onUploaded = vi.fn(), onFormatChange = vi.fn()) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <Dropzone onUploaded={onUploaded} onFormatChange={onFormatChange} />
    </QueryClientProvider>,
  );
  return { onUploaded, onFormatChange };
}

beforeEach(() => {
  vi.clearAllMocks();
});

it("dragover preventDefault and drop triggers uploadJob", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.uploadJob).mockResolvedValue({ id: 42, status: "queued" });
  const { onUploaded } = renderDropzone();
  await screen.findByTestId("btn-upload");
  const file = new File(["x"], "a.txt", { type: "text/plain" });
  const dz = screen.getByTestId("dropzone");
  const over = createEvent.dragOver(dz, { cancelable: true, dataTransfer: { files: [] } });
  fireEvent(dz, over);
  expect(over.defaultPrevented).toBe(true);
  fireEvent.drop(dz, { dataTransfer: { files: [file] } });
  await waitFor(() => expect(api.uploadJob).toHaveBeenCalledWith(file, { output_format: "md" }));
  await waitFor(() => expect(onUploaded).toHaveBeenCalledWith({ id: 42, status: "queued" }));
  // R59: upload success toast fires alongside inline behaviors.
  expect(toast.success).toHaveBeenCalledWith("Đã tải lên — đang chờ xử lý.");
});

it("image selection opens crop wizard instead of eager upload", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  renderDropzone();
  await screen.findByTestId("btn-upload");
  // jsdom has no URL.createObjectURL — stub for the wizard's <img src>.
  Object.defineProperty(URL, "createObjectURL", {
    value: vi.fn(() => "blob:mock"),
    configurable: true,
    writable: true,
  });
  Object.defineProperty(URL, "revokeObjectURL", { value: vi.fn(), configurable: true, writable: true });
  const file = new File(["x"], "photo.png", { type: "image/png" });
  fireEvent.change(screen.getByTestId("input-file"), { target: { files: [file] } });
  await screen.findByTestId("wizard-image");
  expect(screen.queryByTestId("input-file")).not.toBeInTheDocument();
  expect(api.uploadJob).not.toHaveBeenCalled();
  // cancel → back to empty dropzone
  fireEvent.click(screen.getByTestId("wizard-cancel"));
  await screen.findByTestId("input-file");
  expect(screen.queryByTestId("wizard-image")).not.toBeInTheDocument();
});

it("pdf selection opens wizard instead of immediate upload", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.uploadJob).mockResolvedValue({ id: 42, status: "queued" });
  renderDropzone();
  await screen.findByTestId("btn-upload");
  const file = new File(["%PDF-1.7"], "a.pdf", { type: "application/pdf" });
  fireEvent.change(screen.getByTestId("input-file"), { target: { files: [file] } });
  await screen.findByTestId("wizard-pdf");
  expect(screen.queryByTestId("input-file")).not.toBeInTheDocument();
  expect(api.uploadJob).not.toHaveBeenCalled();
  // cancel → back to empty dropzone
  fireEvent.click(screen.getByTestId("wizard-cancel"));
  await screen.findByTestId("input-file");
  expect(screen.queryByTestId("wizard-pdf")).not.toBeInTheDocument();
});

it("drop uploads nothing when ocr not enabled", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: false } as User);
  renderDropzone();
  const banner = await screen.findByTestId("banner-no-access");
  expect(banner).toHaveTextContent("Chờ admin cấp quyền");
  // Task: dev first-run hint — admin cannot self-grant via bootstrap; banner explains the path.
  expect(banner).toHaveTextContent("đăng nhập tài khoản admin");
  const file = new File(["x"], "a.jpg", { type: "image/jpeg" });
  fireEvent.drop(screen.getByTestId("dropzone"), { dataTransfer: { files: [file] } });
  expect(api.uploadJob).not.toHaveBeenCalled();
});

// --- Stale-state guards: a NEW file selection must reset wizard state ---
// Bug: upload sent the PREVIOUS file's bytes after the user selected another file
// (crop rect/dims + preview bitmap + pdf doc persisted across the file swap).

it("selecting image B while crop wizard holds A resets crop state — submits B untouched", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.uploadJob).mockResolvedValue({ id: 42, status: "queued" });
  renderDropzone();
  await screen.findByTestId("btn-upload");
  // jsdom: stub object URL + canvas like ImageCropWizard.test.tsx
  Object.defineProperty(URL, "createObjectURL", {
    value: vi.fn(() => "blob:mock"),
    configurable: true,
    writable: true,
  });
  Object.defineProperty(URL, "revokeObjectURL", { value: vi.fn(), configurable: true, writable: true });
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
    drawImage: vi.fn(), fillRect: vi.fn(), strokeRect: vi.fn(), save: vi.fn(), restore: vi.fn(),
    translate: vi.fn(), rotate: vi.fn(), scale: vi.fn(), fillStyle: "", strokeStyle: "",
  } as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLCanvasElement.prototype, "getBoundingClientRect").mockReturnValue({
    x: 0, y: 0, left: 0, top: 0, right: 400, bottom: 300, width: 400, height: 300,
    toJSON: () => ({}),
  } as DOMRect);
  vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation((cb) =>
    cb(new Blob([new Uint8Array([1, 2, 3])], { type: "image/jpeg" })),
  );

  const a = new File(["A"], "hoa.png", { type: "image/png" });
  const b = new File(["B"], "van.png", { type: "image/png" });
  // File A opens the crop wizard; load dims, draw a crop rect
  fireEvent.change(screen.getByTestId("input-file"), { target: { files: [a] } });
  const img = await screen.findByTestId("wizard-image");
  Object.defineProperty(img, "naturalWidth", { value: 800, configurable: true });
  Object.defineProperty(img, "naturalHeight", { value: 600, configurable: true });
  fireEvent.load(img);
  const canvas = screen.getByTestId("crop-canvas");
  fireEvent.pointerDown(canvas, { clientX: 50, clientY: 50 });
  fireEvent.pointerMove(canvas, { clientX: 150, clientY: 125 });
  fireEvent.pointerUp(canvas, { clientX: 150, clientY: 125 });
  // File B arrives while the wizard is open (drag & drop onto the dropzone)
  fireEvent.drop(screen.getByTestId("dropzone"), { dataTransfer: { files: [b] } });
  await screen.findByTestId("wizard-crop");
  fireEvent.click(screen.getByTestId("wizard-submit"));
  await waitFor(() => expect(api.uploadJob).toHaveBeenCalledTimes(1));
  // Stale crop rect (from A) must not crop B — the NEW file uploads as-is.
  expect(vi.mocked(api.uploadJob).mock.calls[0][0]).toBe(b);
});

it("selecting pdf B while pdf wizard holds A reloads the document — pages come from B", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.uploadJob).mockResolvedValue({ id: 43, status: "queued" });
  // A: 3-page pdf → B: 1-page pdf
  vi.mocked(loadPdf)
    .mockResolvedValueOnce({
      numPages: 3,
      getPage: vi.fn(async () => ({ viewport: { width: 10, height: 10 }, renderCanvas: vi.fn() })),
    } as never)
    .mockResolvedValueOnce({
      numPages: 1,
      getPage: vi.fn(async () => ({ viewport: { width: 10, height: 10 }, renderCanvas: vi.fn() })),
    } as never);
  renderDropzone();
  await screen.findByTestId("btn-upload");
  const a = new File(["%PDF-1.7 a"], "hoa.pdf", { type: "application/pdf" });
  const b = new File(["%PDF-1.7 b"], "van.pdf", { type: "application/pdf" });
  fireEvent.change(screen.getByTestId("input-file"), { target: { files: [a] } });
  await screen.findByTestId("wizard-page-3"); // A's 3 pages rendered
  fireEvent.drop(screen.getByTestId("dropzone"), { dataTransfer: { files: [b] } });
  await screen.findByTestId("wizard-pdf");
  // B's document is 1 page — A's page list must not survive the swap.
  expect(screen.queryByTestId("wizard-page-3")).not.toBeInTheDocument();
  fireEvent.click(screen.getByTestId("wizard-submit"));
  await waitFor(() => expect(api.uploadJob).toHaveBeenCalledTimes(1));
  expect(vi.mocked(api.uploadJob).mock.calls[0][0]).toBe(b);
  expect(vi.mocked(api.uploadJob).mock.calls[0][1]).toEqual({
    preprocess: { pages: [1], rotate: {} },
    output_format: "md",
  });
});
