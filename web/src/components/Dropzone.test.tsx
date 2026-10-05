import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createEvent, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { toast } from "sonner";
import { api } from "../api/client";
import type { User } from "../api/types";
import Dropzone from "./Dropzone";

// R30: pdfjs mocked at module boundary — pdf wizard never loads real pdfjs in tests.
vi.mock("../lib/pdfjs", () => ({
  loadPdf: vi.fn(async () => ({
    numPages: 1,
    getPage: vi.fn(async () => ({ viewport: { width: 10, height: 10 }, renderCanvas: vi.fn() })),
  })),
}));

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
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

function renderDropzone(onUploaded = vi.fn()) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <Dropzone onUploaded={onUploaded} />
    </QueryClientProvider>,
  );
  return onUploaded;
}

beforeEach(() => {
  vi.clearAllMocks();
});

it("dragover preventDefault and drop triggers uploadJob", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.uploadJob).mockResolvedValue({ id: 42, status: "queued" });
  const onUploaded = renderDropzone();
  await screen.findByTestId("btn-upload");
  const file = new File(["x"], "a.txt", { type: "text/plain" });
  const dz = screen.getByTestId("dropzone");
  const over = createEvent.dragOver(dz, { cancelable: true, dataTransfer: { files: [] } });
  fireEvent(dz, over);
  expect(over.defaultPrevented).toBe(true);
  fireEvent.drop(dz, { dataTransfer: { files: [file] } });
  await waitFor(() => expect(api.uploadJob).toHaveBeenCalledWith(file));
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
