import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../src/api/client";
import { ApiError } from "../../src/api/client";
import IrViewer from "../../src/components/IrViewer";

vi.mock("../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/api/client")>();
  return { ...actual, api: { ...actual.api, getIr: vi.fn() } };
});

function renderViewer(status: "done" | "queued" | "failed" = "done") {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <IrViewer jobId={5} status={status} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

it("open → lazy fetch + pretty JSON shows document_id + copy button", async () => {
  vi.mocked(api.getIr).mockResolvedValue({ document_id: "doc-9", zones: [] });
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  renderViewer();
  expect(api.getIr).not.toHaveBeenCalled();
  await userEvent.click(screen.getByTestId("ir-viewer-toggle"));
  expect(await screen.findByTestId("ir-viewer-pre")).toHaveTextContent("document_id");
  expect(api.getIr).toHaveBeenCalledWith(5);
  expect(screen.getByTestId("ir-viewer-copy")).toBeInTheDocument();
  await userEvent.click(screen.getByTestId("ir-viewer-copy"));
  expect(writeText).toHaveBeenCalled();
});

it("done nhưng 409 (chưa render IR) → ẩn nút copy, hiện alert", async () => {
  vi.mocked(api.getIr).mockRejectedValue(new ApiError("Chưa có IR."));
  renderViewer("done");
  await userEvent.click(screen.getByTestId("ir-viewer-toggle"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Chưa có IR.");
  expect(screen.queryByTestId("ir-viewer-copy")).not.toBeInTheDocument();
});

it("status ≠ done → ẩn toàn bộ viewer (không nút toggle)", () => {
  renderViewer("queued");
  expect(screen.queryByTestId("ir-viewer")).not.toBeInTheDocument();
  expect(screen.queryByTestId("ir-viewer-toggle")).not.toBeInTheDocument();
});
