import { PDFDocument } from "pdf-lib";

/** Tổng trang cho 1 job gộp — chặn trước khi ghép (spec U2). */
export const MAX_PAGES = 25;

export interface MergeEntry {
  kind: "image" | "pdf";
  blob: Blob;
  name: string;
  /** PDF: trang đã chọn (1-based); ảnh bỏ qua. */
  pages?: number[];
}

/** Gộp N ảnh (đã crop) + PDF (trang đã chọn) → 1 PDF; ảnh trước, PDF sau. */
export async function mergeToPdf(entries: MergeEntry[]): Promise<Blob> {
  const out = await PDFDocument.create();
  const images = entries.filter((e) => e.kind === "image");
  const pdfs = entries.filter((e) => e.kind === "pdf");
  for (const e of images) {
    const bytes = new Uint8Array(await e.blob.arrayBuffer());
    const img = e.blob.type === "image/png" ? await out.embedPng(bytes) : await out.embedJpg(bytes);
    const page = out.addPage([img.width, img.height]);
    page.drawImage(img, { x: 0, y: 0, width: img.width, height: img.height });
  }
  for (const e of pdfs) {
    const src = await PDFDocument.load(await e.blob.arrayBuffer());
    const idx = e.pages?.length ? e.pages.map((n) => n - 1) : src.getPageIndices();
    const copied = await out.copyPages(src, idx);
    for (const p of copied) out.addPage(p);
  }
  if (out.getPageCount() > MAX_PAGES) {
    throw new Error(`Tối đa ${MAX_PAGES} trang mỗi lần gửi.`);
  }
  const bytes = await out.save();
  return new Blob(
    [bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer],
    { type: "application/pdf" },
  );
}
