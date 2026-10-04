import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { ApiError, api } from "../api/client";
import ExportBar from "./ExportBar";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      exportJob: vi.fn(),
    },
  };
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

it("four export buttons exist and call api with fmt", async () => {
  vi.mocked(api.exportJob).mockResolvedValue({ url: "https://r2/exports/5/docx" });
  const open = vi.fn();
  vi.stubGlobal("open", open);
  render(<ExportBar jobId="5" />);
  for (const fmt of ["md", "html", "docx", "pdf"]) {
    expect(screen.getByTestId(`export-${fmt}`)).toBeInTheDocument();
  }
  await userEvent.click(screen.getByTestId("export-docx"));
  expect(api.exportJob).toHaveBeenCalledWith("5", "docx");
  await waitFor(() =>
    expect(open).toHaveBeenCalledWith("https://r2/exports/5/docx", "_blank"),
  );
});

it("shows ApiError detail when export fails", async () => {
  vi.mocked(api.exportJob).mockRejectedValue(new ApiError("Xuất file thất bại."));
  render(<ExportBar jobId="5" />);
  await userEvent.click(screen.getByTestId("export-pdf"));
  expect(await screen.findByTestId("export-error")).toHaveTextContent(
    "Xuất file thất bại.",
  );
});
