import { describe, expect, it } from "vitest";
import { PDFDocument } from "pdf-lib";
import { mergeToPdf, MAX_PAGES } from "../../src/hooks/useImageToPdf";

// Valid 1×1 PNG (real bytes — pdf-lib parses the chunk structure).
const PNG_1x1 = Uint8Array.from(
  atob(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  ),
  (c) => c.charCodeAt(0),
);

const png = () =>
  new Blob([PNG_1x1.buffer.slice(PNG_1x1.byteOffset, PNG_1x1.byteOffset + PNG_1x1.byteLength) as ArrayBuffer], {
    type: "image/png",
  });

async function makePdf(pages: number): Promise<Blob> {
  const doc = await PDFDocument.create();
  for (let i = 0; i < pages; i++) doc.addPage([100, 100]);
  const bytes = await doc.save();
  return new Blob(
    [bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer],
    { type: "application/pdf" },
  );
}

describe("mergeToPdf", () => {
  it("ghép 2 ảnh → 1 PDF, 2 trang", async () => {
    const blob = await mergeToPdf([
      { kind: "image", blob: png(), name: "a.png" },
      { kind: "image", blob: png(), name: "b.png" },
    ]);
    expect(blob.type).toBe("application/pdf");
    const out = await PDFDocument.load(await blob.arrayBuffer());
    expect(out.getPageCount()).toBe(2);
  });

  it("mixed ảnh + PDF → append (ảnh trước, PDF sau)", async () => {
    const blob = await mergeToPdf([
      { kind: "image", blob: png(), name: "a.png" },
      { kind: "pdf", blob: await makePdf(3), name: "b.pdf", pages: [1, 3] },
    ]);
    const out = await PDFDocument.load(await blob.arrayBuffer());
    expect(out.getPageCount()).toBe(3); // 1 ảnh + 2 trang đã chọn
  });

  it("P1-2: pages:[] → 0 trang, không fallback all", async () => {
    const blob = await mergeToPdf([
      { kind: "image", blob: png(), name: "a.png" },
      { kind: "pdf", blob: await makePdf(3), name: "b.pdf", pages: [] },
    ]);
    const out = await PDFDocument.load(await blob.arrayBuffer());
    expect(out.getPageCount()).toBe(1); // ảnh 1 + PDF 0 trang (không phải 4)
  });

  it("P1-1: ảnh không phải PNG/JPG → ném lỗi rõ", async () => {
    const webp = new Blob([new Uint8Array([0, 1, 2])], { type: "image/webp" });
    await expect(mergeToPdf([{ kind: "image", blob: webp, name: "a.webp" }])).rejects.toThrow(
      /PNG\/JPG/,
    );
  });

  it("P2: cap check trước embed — over-cap pdf + ảnh lỗi → ném /25/ (không lỗi embed)", async () => {
    const webp = new Blob([new Uint8Array([0, 1, 2])], { type: "image/webp" });
    await expect(
      mergeToPdf([
        { kind: "image", blob: webp, name: "a.webp" },
        {
          kind: "pdf",
          blob: await makePdf(30),
          name: "b.pdf",
          pages: Array.from({ length: 30 }, (_, i) => i + 1),
        },
      ]),
    ).rejects.toThrow(/25/);
  });

  it(`quá ${MAX_PAGES} trang → ném lỗi`, async () => {
    const entries = Array.from({ length: MAX_PAGES + 1 }, (_, i) => ({
      kind: "image" as const,
      blob: png(),
      name: `${i}.png`,
    }));
    await expect(mergeToPdf(entries)).rejects.toThrow(/25/);
  });
});
