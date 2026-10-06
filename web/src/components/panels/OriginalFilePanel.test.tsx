import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { ApiError, api } from "../../api/client";
import OriginalFilePanel from "./OriginalFilePanel";

vi.mock("../../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      downloadJobFile: vi.fn(),
    },
  };
});

function renderPanel(fileType: string): ReturnType<typeof render> {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const ui: ReactElement = (
    <QueryClientProvider client={queryClient}>
      <OriginalFilePanel jobId="5" fileType={fileType} />
    </QueryClientProvider>
  );
  return render(ui);
}

beforeEach(() => {
  vi.clearAllMocks();
  // jsdom lacks blob URL APIs (Plan V: viewer/download go through objectURL).
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:http://test/5");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
});

it("lazy: downloadJobFile called ONLY after expand; caches blob url on re-expand", async () => {
  vi.mocked(api.downloadJobFile).mockResolvedValue(new Blob(["png"]));
  renderPanel("image");
  expect(screen.getByTestId("panel-original")).toBeInTheDocument();
  expect(api.downloadJobFile).not.toHaveBeenCalled();
  const user = userEvent.setup();
  await user.click(screen.getByTestId("toggle-original"));
  await waitFor(() => expect(api.downloadJobFile).toHaveBeenCalledWith("5"));
  const img = await screen.findByAltText("File gốc");
  expect(img).toHaveAttribute("src", "blob:http://test/5");
  // Collapse hides viewer; re-expand must NOT refetch (lazy = once).
  await user.click(screen.getByTestId("toggle-original"));
  expect(screen.queryByAltText("File gốc")).toBeNull();
  await user.click(screen.getByTestId("toggle-original"));
  expect(api.downloadJobFile).toHaveBeenCalledTimes(1);
});

it("image renders original-image testid with blob: src", async () => {
  vi.mocked(api.downloadJobFile).mockResolvedValue(new Blob(["png"]));
  renderPanel("image");
  await userEvent.setup().click(screen.getByTestId("toggle-original"));
  const img = await screen.findByTestId("original-image");
  expect(img).toHaveAttribute("src", expect.stringMatching(/^blob:/));
});

it("pdf renders sandboxed iframe with a11y title + blob new-tab link", async () => {
  vi.mocked(api.downloadJobFile).mockResolvedValue(new Blob(["pdf"]));
  renderPanel("pdf");
  const user = userEvent.setup();
  await user.click(screen.getByTestId("toggle-original"));
  const frame = await screen.findByTitle("File gốc");
  expect(frame).toHaveAttribute("src", "blob:http://test/5");
  expect(frame).toHaveAttribute("sandbox", "");
  const link = screen.getByRole("link", { name: "Mở tab mới" });
  expect(link).toHaveAttribute("href", "blob:http://test/5");
  expect(link).toHaveAttribute("target", "_blank");
});

it("shows loading skeleton while fetching", async () => {
  vi.mocked(api.downloadJobFile).mockReturnValue(new Promise(() => {}));
  renderPanel("image");
  const user = userEvent.setup();
  await user.click(screen.getByTestId("toggle-original"));
  expect(await screen.findByTestId("original-loading")).toBeInTheDocument();
});

it("shows ApiError detail on fetch failure", async () => {
  vi.mocked(api.downloadJobFile).mockRejectedValue(new ApiError("Không có file."));
  renderPanel("image");
  const user = userEvent.setup();
  await user.click(screen.getByTestId("toggle-original"));
  expect(await screen.findByTestId("original-error")).toHaveTextContent("Không có file.");
  expect(screen.queryByAltText("File gốc")).toBeNull();
});

it("btn-download-original fetches blob, createObjectURL + anchor click + revoke", async () => {
  vi.mocked(api.downloadJobFile).mockResolvedValue(new Blob(["png"]));
  const clickSpy = vi
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => {});
  renderPanel("image");
  await userEvent.setup().click(screen.getByTestId("btn-download-original"));
  expect(api.downloadJobFile).toHaveBeenCalledWith("5");
  await waitFor(() =>
    expect(URL.createObjectURL).toHaveBeenCalledWith(expect.any(Blob))
  );
  expect(clickSpy).toHaveBeenCalledTimes(1);
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:http://test/5");
});
