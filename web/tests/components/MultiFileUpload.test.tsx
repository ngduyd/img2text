import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { PDFDocument } from "pdf-lib";
import { toast } from "sonner";
import MultiFileUpload from "../../src/components/MultiFileUpload";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("../../src/lib/pdfjs", () => ({
  // 0 trang (zero.pdf) để dựng total = 0; còn lại 3 trang.
  loadPdf: vi.fn(async (f: File) => ({
    numPages: f.name.startsWith("zero") ? 0 : 3,
    getPage: vi.fn(),
  })),
}));

// jsdom thiếu object URL cho <img src> thumbnail — url duy nhất per blob.
let urlSeq = 0;
beforeEach(() => {
  vi.clearAllMocks();
  urlSeq = 0;
  Object.defineProperty(URL, "createObjectURL", {
    value: vi.fn(() => `blob:${++urlSeq}`),
    configurable: true,
    writable: true,
  });
  Object.defineProperty(URL, "revokeObjectURL", { value: vi.fn(), configurable: true, writable: true });
});

const img = (n: string) => new File(["x"], n, { type: "image/png" });

async function pdfBlob(pages: number): Promise<File> {
  const doc = await PDFDocument.create();
  for (let i = 0; i < pages; i++) doc.addPage([100, 100]);
  const bytes = await doc.save();
  const part = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
  return new File([part], "a.pdf", { type: "application/pdf" });
}

function add(files: File[]) {
  fireEvent.change(screen.getByTestId("muf-input"), { target: { files } });
}

it("empty state: 'Tải file lên' + 'Kéo thả file vào'; thêm N file → N cards", () => {
  render(<MultiFileUpload onSubmit={vi.fn()} />);
  expect(screen.getByText("Tải file lên")).toBeInTheDocument();
  expect(screen.getByText(/Kéo thả file vào/)).toBeInTheDocument();
  add([img("a.png"), img("b.png"), img("c.png")]);
  expect(screen.getAllByTestId(/muf-card-/)).toHaveLength(3);
});

it("Xóa xóa đúng card", () => {
  render(<MultiFileUpload onSubmit={vi.fn()} />);
  add([img("a.png"), img("b.png")]);
  fireEvent.click(screen.getByTestId("muf-remove-0"));
  expect(screen.getAllByTestId(/muf-card-/)).toHaveLength(1);
  expect(screen.getByText("b.png")).toBeInTheDocument();
});

it("quá 25 trang → chặn + toast.error, giữ 25 card", () => {
  render(<MultiFileUpload onSubmit={vi.fn()} />);
  add(Array.from({ length: 26 }, (_, i) => img(`${i}.png`)));
  expect(screen.getAllByTestId(/muf-card-/)).toHaveLength(25);
  expect(toast.error).toHaveBeenCalled();
});

it("P1-1: accept chỉ png/jpg/pdf — webp bị reject, không nhận", () => {
  render(<MultiFileUpload onSubmit={vi.fn()} />);
  expect(screen.getByTestId("muf-input")).toHaveAttribute(
    "accept",
    "image/png,image/jpeg,application/pdf",
  );
  add([new File(["x"], "a.webp", { type: "image/webp" })]);
  expect(screen.queryAllByTestId(/muf-card-/)).toHaveLength(0);
  expect(toast.error).toHaveBeenCalled();
});

it("P1-2: deselect-all → giữ selection cũ, không merge full PDF", async () => {
  const onSelectPages = vi
    .fn()
    .mockResolvedValueOnce([1, 3])
    .mockResolvedValueOnce([]);
  const onSubmit = vi.fn();
  render(<MultiFileUpload onSubmit={onSubmit} onSelectPages={onSelectPages} />);
  add([await pdfBlob(3)]);
  await waitFor(() => expect(screen.getByTestId("muf-card-0")));
  fireEvent.click(screen.getByTestId("muf-pages-0"));
  fireEvent.click(screen.getByTestId("muf-pages-0")); // deselect-all
  await waitFor(() => expect(screen.getByText("2/3 trang")).toBeInTheDocument());
  fireEvent.click(screen.getByTestId("muf-submit"));
  await waitFor(() => expect(onSubmit).toHaveBeenCalled());
  const meta = onSubmit.mock.calls[0][1];
  expect(meta.page_count).toBe(2);
  const out = await PDFDocument.load(await (onSubmit.mock.calls[0][0] as Blob).arrayBuffer());
  expect(out.getPageCount()).toBe(2);
});

it("P1: filename payload = tên gốc, không hardcode tong-hop.pdf", async () => {
  const onSubmit = vi.fn();
  render(<MultiFileUpload onSubmit={onSubmit} />);
  add([await pdfBlob(3)]); // tên gốc "a.pdf"
  await waitFor(() => expect(screen.getByTestId("muf-card-0")));
  fireEvent.click(screen.getByTestId("muf-submit"));
  await waitFor(() => expect(onSubmit).toHaveBeenCalled());
  expect(onSubmit.mock.calls[0][1].filename).toBe("a.pdf");
});

it("P2: total = 0 trang → disable nút Gửi", async () => {
  render(<MultiFileUpload onSubmit={vi.fn()} />);
  add([new File(["x"], "zero.pdf", { type: "application/pdf" })]);
  await waitFor(() => expect(screen.getByTestId("muf-card-0")));
  expect(screen.getAllByTestId(/muf-card-/)).toHaveLength(1);
  expect(screen.getByTestId("muf-submit")).toBeDisabled();
});

it("P2: crop → revoke thumbnail cũ, store url mới", async () => {
  const onCrop = vi.fn(async () => new Blob(["y"], { type: "image/png" }));
  render(<MultiFileUpload onSubmit={vi.fn()} onCrop={onCrop} />);
  add([img("a.png")]); // url blob:1
  fireEvent.click(screen.getByTestId("muf-crop-0"));
  await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:1"));
  expect(screen.getByAltText("a.png")).toHaveAttribute("src", "blob:2");
});

it("P2 DESIGN: badge rounded-full, card rounded-card", async () => {
  render(<MultiFileUpload onSubmit={vi.fn()} />);
  add([await pdfBlob(3)]);
  await waitFor(() => expect(screen.getByText("PDF")));
  expect(screen.getByText("PDF")).toHaveClass("rounded-full");
  const card = screen.getByTestId("muf-card-0");
  expect(card).toHaveClass("rounded-card");
  expect(card).not.toHaveClass("rounded-md");
});
