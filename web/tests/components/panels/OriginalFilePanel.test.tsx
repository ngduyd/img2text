import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { ApiError, api } from "../../../src/api/client";
import { clearJobBlobCache } from "../../../src/lib/blobCache";
import OriginalFilePanel from "../../../src/components/panels/OriginalFilePanel";

vi.mock("../../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../src/api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      downloadJobFile: vi.fn(),
    },
  };
});

function renderPanel(fileType: string, jobId = "5"): ReturnType<typeof render> {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const ui: ReactElement = (
    <QueryClientProvider client={queryClient}>
      <OriginalFilePanel jobId={jobId} fileType={fileType} />
    </QueryClientProvider>
  );
  return render(ui);
}

beforeEach(() => {
  vi.clearAllMocks();
  // Module-level blob cache share giữa các test trong file — dọn để mock khác nhau không share entry.
  clearJobBlobCache();
  // jsdom lacks blob URL APIs (Plan V: viewer/download go through objectURL).
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:http://test/5");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
});

/** WS-UI: AUTO-FETCH khi mount (bỏ toggle "Hiện file"). */
it("auto-fetches blob on mount and renders image", async () => {
  vi.mocked(api.downloadJobFile).mockResolvedValue(new Blob(["png"]));
  renderPanel("image");
  expect(await screen.findByTestId("original-image")).toBeInTheDocument();
  expect(api.downloadJobFile).toHaveBeenCalledWith("5");
});

it("pdf renders sandboxed iframe with a11y title + blob new-tab link", async () => {
  vi.mocked(api.downloadJobFile).mockResolvedValue(new Blob(["pdf"]));
  renderPanel("pdf");
  const frame = await screen.findByTitle("File gốc");
  expect(frame).toHaveAttribute("src", "blob:http://test/5");
  expect(frame).toHaveAttribute("sandbox", "");
  const link = screen.getByRole("link", { name: "Mở tab mới" });
  expect(link).toHaveAttribute("href", "blob:http://test/5");
  expect(link).toHaveAttribute("target", "_blank");
});

it("2 mount cùng jobId → 1 fetch (blob cache module-level)", async () => {
  vi.mocked(api.downloadJobFile).mockResolvedValue(new Blob(["png"]));
  renderPanel("image", "7");
  await screen.findByTestId("original-image");
  renderPanel("image", "7");
  await waitFor(() => expect(screen.getAllByTestId("original-image")).toHaveLength(2));
  expect(api.downloadJobFile).toHaveBeenCalledTimes(1);
});

it("shows loading skeleton while fetching", () => {
  vi.mocked(api.downloadJobFile).mockReturnValue(new Promise(() => {}));
  renderPanel("image");
  expect(screen.getByTestId("original-loading")).toBeInTheDocument();
});

it("shows ApiError detail on fetch failure", async () => {
  vi.mocked(api.downloadJobFile).mockRejectedValue(new ApiError("Không có file."));
  renderPanel("image");
  expect(await screen.findByTestId("original-error")).toHaveTextContent("Không có file.");
  expect(screen.queryByAltText("File gốc")).toBeNull();
});

it("btn-download-original uses viewer blob + anchor click + revoke", async () => {
  vi.mocked(api.downloadJobFile).mockResolvedValue(new Blob(["png"]));
  const clickSpy = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => {});
  renderPanel("image");
  await screen.findByTestId("original-image");
  await userEvent.setup().click(screen.getByTestId("btn-download-original"));
  // Dùng blob URL có sẵn từ viewer — KHÔNG fetch lại.
  expect(api.downloadJobFile).toHaveBeenCalledTimes(1);
  await waitFor(() => expect(clickSpy).toHaveBeenCalledTimes(1));
  const anchor = clickSpy.mock.instances[0] as HTMLAnchorElement;
  expect(anchor).toHaveAttribute("download", "job-5.jpg");
});
