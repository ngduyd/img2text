import * as pdfjs from "pdfjs-dist";
import type { PDFDocumentProxy } from "pdfjs-dist";

// Vite module-worker pattern; pdf.worker ships as its own asset chunk.
// Guard: jsdom suites that don't mock ../lib/pdfjs never need a worker.
if (typeof Worker !== "undefined") {
  pdfjs.GlobalWorkerOptions.workerPort = new Worker(
    new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url),
    { type: "module" },
  );
}

/** Thumbnail scale for the wizard page list — one knob for all pages. */
const THUMB_SCALE = 0.3;

export interface PdfThumbPage {
  viewport: { width: number; height: number };
  renderCanvas: (canvas: HTMLCanvasElement) => Promise<void>;
}

export interface PdfDoc {
  numPages: number;
  getPage: (n: number) => Promise<PdfThumbPage>;
}

/** Thin pdfjs-dist boundary — components import ONLY this; tests vi.mock it (R30). */
export async function loadPdf(file: File): Promise<PdfDoc> {
  const data = new Uint8Array(await file.arrayBuffer());
  const doc: PDFDocumentProxy = await pdfjs.getDocument({ data }).promise;
  return {
    numPages: doc.numPages,
    getPage: async (n: number): Promise<PdfThumbPage> => {
      const page = await doc.getPage(n);
      const viewport = page.getViewport({ scale: THUMB_SCALE });
      return {
        viewport: { width: viewport.width, height: viewport.height },
        renderCanvas: async (canvas: HTMLCanvasElement) => {
          canvas.width = viewport.width;
          canvas.height = viewport.height;
          await page.render({ canvas, viewport }).promise;
        },
      };
    },
  };
}
