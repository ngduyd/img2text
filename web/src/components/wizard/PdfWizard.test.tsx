import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../api/client";
import { loadPdf } from "../../lib/pdfjs";
import PdfWizard from "./PdfWizard";

const { renderCanvas } = vi.hoisted(() => ({ renderCanvas: vi.fn(async () => {}) }));

// R30: mock the pdfjs module boundary wholesale — real pdfjs never loads in tests.
vi.mock("../../lib/pdfjs", () => ({
  loadPdf: vi.fn(async () => ({
    numPages: 3,
    getPage: vi.fn(async () => ({ viewport: { width: 60, height: 80 }, renderCanvas })),
  })),
}));

vi.mock("../../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/client")>();
  return { ...actual, api: { ...actual.api, uploadJob: vi.fn() } };
});

const file = new File(["%PDF-1.7"], "doc.pdf", { type: "application/pdf" });

function renderWizard(onCancel = vi.fn(), onUploaded = vi.fn()) {
  render(<PdfWizard file={file} onCancel={onCancel} onUploaded={onUploaded} />);
  return { onCancel, onUploaded };
}

beforeEach(() => {
  vi.clearAllMocks();
  // jsdom has no real 2D canvas — thumbnails come from the mocked renderCanvas.
  vi.spyOn(HTMLCanvasElement.prototype, "toDataURL").mockReturnValue("data:image/png;base64,x");
});

it("renders 3 page rows, all checkboxes default checked, thumbnails rendered", async () => {
  renderWizard();
  expect(screen.getByTestId("wizard-pdf")).toBeInTheDocument();
  await screen.findByTestId("wizard-page-3");
  for (const n of [1, 2, 3]) {
    const row = screen.getByTestId(`wizard-page-${n}`);
    expect(row.querySelector("input[type=checkbox]")).toBeChecked();
    expect(screen.getByTestId(`wizard-rotate-${n}`)).toHaveValue("0");
  }
  expect(vi.mocked(loadPdf)).toHaveBeenCalledWith(file);
  await waitFor(() => expect(renderCanvas).toHaveBeenCalledTimes(3));
  for (const n of [1, 2, 3]) {
    await waitFor(() =>
      expect(screen.getByTestId(`wizard-page-${n}`).querySelector("img")).toHaveAttribute(
        "src",
        "data:image/png;base64,x",
      ),
    );
  }
});

it("uncheck page 2 → submit uploads original File with preprocess pages [1,3]", async () => {
  const { onUploaded } = renderWizard();
  vi.mocked(api.uploadJob).mockResolvedValue({ id: 7, status: "queued" });
  await screen.findByTestId("wizard-page-1");
  fireEvent.click(screen.getByTestId("wizard-page-2").querySelector("input[type=checkbox]")!);
  fireEvent.click(screen.getByTestId("wizard-submit"));
  await waitFor(() =>
    expect(api.uploadJob).toHaveBeenCalledWith(file, { preprocess: { pages: [1, 3], rotate: {} } }),
  );
  await waitFor(() => expect(onUploaded).toHaveBeenCalledWith({ id: 7, status: "queued" }));
});

it("rotate page 3 to 90 → submit preprocess rotate {3:90}", async () => {
  renderWizard();
  await screen.findByTestId("wizard-page-3");
  fireEvent.change(screen.getByTestId("wizard-rotate-3"), { target: { value: "90" } });
  fireEvent.click(screen.getByTestId("wizard-submit"));
  await waitFor(() =>
    expect(api.uploadJob).toHaveBeenCalledWith(file, {
      preprocess: { pages: [1, 2, 3], rotate: { "3": 90 } },
    }),
  );
});

it("empty selection → wizard-error shown, uploadJob NOT called", async () => {
  renderWizard();
  await screen.findByTestId("wizard-page-1");
  for (const n of [1, 2, 3]) {
    fireEvent.click(screen.getByTestId(`wizard-page-${n}`).querySelector("input[type=checkbox]")!);
  }
  fireEvent.click(screen.getByTestId("wizard-submit"));
  expect(await screen.findByTestId("wizard-error")).toHaveTextContent("Chưa chọn trang nào.");
  expect(api.uploadJob).not.toHaveBeenCalled();
});

it("cancel calls onCancel", async () => {
  const { onCancel } = renderWizard();
  await screen.findByTestId("wizard-page-1");
  fireEvent.click(screen.getByTestId("wizard-cancel"));
  expect(onCancel).toHaveBeenCalledTimes(1);
  expect(api.uploadJob).not.toHaveBeenCalled();
});

// Last test — overrides the shared loadPdf mock with a 51-page doc.
it("more than 50 pages selected → error, uploadJob NOT called", async () => {
  vi.mocked(loadPdf).mockResolvedValue({
    numPages: 51,
    getPage: vi.fn(async () => ({ viewport: { width: 10, height: 10 }, renderCanvas: vi.fn(async () => {}) })),
  });
  renderWizard();
  await screen.findByTestId("wizard-page-51");
  fireEvent.click(screen.getByTestId("wizard-submit"));
  expect(await screen.findByTestId("wizard-error")).toHaveTextContent(
    "Tối đa 50 trang mỗi lần gửi.",
  );
  expect(api.uploadJob).not.toHaveBeenCalled();
});
