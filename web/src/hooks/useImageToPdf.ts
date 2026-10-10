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
  const images = entries.filter((e) => e.kind === "image");
  const pdfs = entries.filter((e) => e.kind === "pdf");

  // Pre-count TRƯỚC embed (P2): chặn cap sớm, không tốn công decode ảnh.
  const docs = await Promise.all(pdfs.map(async (e) => PDFDocument.load(await e.blob.arrayBuffer())));
  const count =
    images.length +
    pdfs.reduce((s, e, i) => s + (e.pages ? e.pages.length : docs[i].getPageCount()), 0);
  if (count > MAX_PAGES) {
    throw new Error(`Tối đa ${MAX_PAGES} trang mỗi lần gửi.`);
  }
  // Defense (P1-1): pdf-lib chỉ embed được PNG/JPG.
  for (const e of images) {
    if (e.blob.type !== "image/png" && e.blob.type !== "image/jpeg") {
      throw new Error("Chỉ hỗ trợ ảnh PNG/JPG.");
    }
  }

  const out = await PDFDocument.create();
  for (const e of images) {
    const bytes = new Uint8Array(await e.blob.arrayBuffer());
    const img = e.blob.type === "image/png" ? await out.embedPng(bytes) : await out.embedJpg(bytes);
    const page = out.addPage([img.width, img.height]);
    page.drawImage(img, { x: 0, y: 0, width: img.width, height: img.height });
  }
  for (let i = 0; i < pdfs.length; i++) {
    const e = pdfs[i];
    const src = docs[i];
    // presence check (không phải truthy): pages:[] = 0 trang, không fallback all.
    const idx = e.pages ? e.pages.map((n) => n - 1) : src.getPageIndices();
    const copied = await out.copyPages(src, idx);
    for (const p of copied) out.addPage(p);
  }
  // Backstop sau embed — giữ như cũ.
  if (out.getPageCount() > MAX_PAGES) {
    throw new Error(`Tối đa ${MAX_PAGES} trang mỗi lần gửi.`);
  }
  const bytes = await out.save();
  return new Blob(
    [bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer],
    { type: "application/pdf" },
  );
}
