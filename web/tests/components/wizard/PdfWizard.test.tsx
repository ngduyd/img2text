import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../../src/api/client";
import { loadPdf } from "../../../src/lib/pdfjs";
import PdfWizard from "../../../src/components/wizard/PdfWizard";

const { renderCanvas } = vi.hoisted(() => ({ renderCanvas: vi.fn(async () => {}) }));

// R30: mock the pdfjs module boundary wholesale — real pdfjs never loads in tests.
vi.mock("../../../src/lib/pdfjs", () => ({
  loadPdf: vi.fn(async () => ({
    numPages: 3,
    getPage: vi.fn(async () => ({ viewport: { width: 60, height: 80 }, renderCanvas })),
  })),
}));

vi.mock("../../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../src/api/client")>();
  return { ...actual, api: { ...actual.api, uploadJob: vi.fn() } };
});

const file = new File(["%PDF-1.7"], "doc.pdf", { type: "application/pdf" });

function renderWizard(onCancel = vi.fn(), onUploaded = vi.fn(), onFormatChange = vi.fn()) {
  render(
    <PdfWizard
      file={file}
      onCancel={onCancel}
      onUploaded={onUploaded}
      onFormatChange={onFormatChange}
    />,
  );
  return { onCancel, onUploaded, onFormatChange };
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
    expect(api.uploadJob).toHaveBeenCalledWith(file, {
      preprocess: { pages: [1, 3], rotate: {} },
      output_format: "md",
      mode: "layout",
    }),
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
      output_format: "md",
      mode: "layout",
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

it("split submit: label reflects outputFormat prop, submit sends that format", async () => {
  render(
    <PdfWizard
      file={file}
      outputFormat="docx"
      onFormatChange={vi.fn()}
      onCancel={vi.fn()}
      onUploaded={vi.fn()}
    />,
  );
  vi.mocked(api.uploadJob).mockResolvedValue({ id: 7, status: "queued" });
  await screen.findByTestId("wizard-page-1");
  expect(screen.getByTestId("wizard-submit")).toHaveTextContent("Gửi lên · Word");
  fireEvent.click(screen.getByTestId("wizard-submit"));
  await waitFor(() =>
    expect(api.uploadJob).toHaveBeenCalledWith(file, {
      preprocess: { pages: [1, 2, 3], rotate: {} },
      output_format: "docx",
      mode: "layout",
    }),
  );
});

it("caret menu: default label Markdown, choosing Word calls onFormatChange and closes menu", async () => {
  const { onFormatChange } = renderWizard();
  await screen.findByTestId("wizard-page-1");
  expect(screen.getByTestId("wizard-submit")).toHaveTextContent("Gửi lên · Markdown");
  fireEvent.click(screen.getByTestId("btn-format-toggle"));
  expect(screen.getByTestId("format-opt-docx")).toBeInTheDocument();
  fireEvent.click(screen.getByTestId("format-opt-docx"));
  expect(onFormatChange).toHaveBeenCalledWith("docx");
  expect(screen.queryByTestId("format-opt-docx")).not.toBeInTheDocument();
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

// Phase 5 (spec E): mode radios + [Hủy][Gửi lên·format▾] cluster top-right; extract_only hides format picker.
it("cluster [Hủy][Gửi lên] sits top-right above the page list; mode radios render", async () => {
  renderWizard();
  await screen.findByTestId("wizard-page-1");
  const cluster = screen.getByTestId("mode-selector").parentElement!;
  expect(cluster).toBe(screen.getByTestId("wizard-pdf").firstElementChild);
  expect(cluster.className).toContain("justify-between");
  expect(cluster).toContainElement(screen.getByTestId("wizard-cancel"));
  expect(cluster).toContainElement(screen.getByTestId("wizard-submit"));
  expect(cluster).toContainElement(screen.getByTestId("btn-format-toggle"));
  // cancel LEFT of submit in the cluster (spec: [Hủy][Gửi lên · format ▾])
  expect(
    screen.getByTestId("wizard-cancel").compareDocumentPosition(screen.getByTestId("wizard-submit")) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  // page list BELOW the cluster
  expect(cluster.compareDocumentPosition(screen.getByTestId("wizard-page-1")) &
    Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

it("extract_only: format picker hidden, submit sends mode", async () => {
  // reset the 51-page doc left by the previous test (clearAllMocks keeps implementations)
  vi.mocked(loadPdf).mockResolvedValue({
    numPages: 3,
    getPage: vi.fn(async () => ({ viewport: { width: 60, height: 80 }, renderCanvas })),
  } as never);
  // controlled: mode owned by the parent Dropzone — render with the prop set
  const onModeChange = vi.fn();
  render(
    <PdfWizard
      file={file}
      mode="extract_only"
      onModeChange={onModeChange}
      onCancel={vi.fn()}
      onUploaded={vi.fn()}
      onFormatChange={vi.fn()}
    />,
  );
  await screen.findByTestId("wizard-page-1");
  expect(screen.getByTestId("mode-extract-only")).toBeChecked();
  expect(screen.queryByTestId("btn-format-toggle")).not.toBeInTheDocument();
  fireEvent.click(screen.getByTestId("wizard-submit"));
  await waitFor(() =>
    expect(api.uploadJob).toHaveBeenCalledWith(file, {
      preprocess: { pages: [1, 2, 3], rotate: {} },
      output_format: "md",
      mode: "extract_only",
    }),
  );
});
