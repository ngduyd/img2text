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
      getJobFile: vi.fn(),
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
});

it("lazy: getJobFile called ONLY after expand; caches url on re-expand", async () => {
  vi.mocked(api.getJobFile).mockResolvedValue({ url: "https://r2/f.png" });
  renderPanel("image");
  expect(screen.getByTestId("panel-original")).toBeInTheDocument();
  expect(api.getJobFile).not.toHaveBeenCalled();
  const user = userEvent.setup();
  await user.click(screen.getByTestId("toggle-original"));
  await waitFor(() => expect(api.getJobFile).toHaveBeenCalledWith("5"));
  const img = await screen.findByAltText("File gốc");
  expect(img).toHaveAttribute("src", "https://r2/f.png");
  // Collapse hides viewer; re-expand must NOT refetch (lazy = once).
  await user.click(screen.getByTestId("toggle-original"));
  expect(screen.queryByAltText("File gốc")).toBeNull();
  await user.click(screen.getByTestId("toggle-original"));
  expect(api.getJobFile).toHaveBeenCalledTimes(1);
});

it("pdf renders iframe with a11y title + new-tab link", async () => {
  vi.mocked(api.getJobFile).mockResolvedValue({ url: "https://r2/f.pdf" });
  renderPanel("pdf");
  const user = userEvent.setup();
  await user.click(screen.getByTestId("toggle-original"));
  const frame = await screen.findByTitle("File gốc PDF");
  expect(frame).toHaveAttribute("src", "https://r2/f.pdf");
  const link = screen.getByRole("link", { name: "Mở tab mới" });
  expect(link).toHaveAttribute("href", "https://r2/f.pdf");
  expect(link).toHaveAttribute("target", "_blank");
});

it("shows loading skeleton while fetching", async () => {
  vi.mocked(api.getJobFile).mockReturnValue(new Promise(() => {}));
  renderPanel("image");
  const user = userEvent.setup();
  await user.click(screen.getByTestId("toggle-original"));
  expect(await screen.findByTestId("original-loading")).toBeInTheDocument();
});

it("shows ApiError detail on fetch failure", async () => {
  vi.mocked(api.getJobFile).mockRejectedValue(new ApiError("Không có file."));
  renderPanel("image");
  const user = userEvent.setup();
  await user.click(screen.getByTestId("toggle-original"));
  expect(await screen.findByTestId("original-error")).toHaveTextContent("Không có file.");
  expect(screen.queryByAltText("File gốc")).toBeNull();
});
