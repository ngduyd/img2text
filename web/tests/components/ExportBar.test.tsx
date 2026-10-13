import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { ApiError, api } from "../../src/api/client";
import ExportBar from "../../src/components/ExportBar";

vi.mock("../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/api/client")>();
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

/** Lane I Task 5: text downloads dời lên header — ExportBar chỉ còn nhóm Layout. */
async function expandLayoutFormats() {
  await userEvent.click(screen.getByTestId("export-layout-more"));
}

it("docx-layout button renders and calls exportJob with docx-layout (D4 review)", async () => {
  vi.mocked(api.exportJob).mockResolvedValue({ url: "https://r2/exports/5/docx-layout" });
  const w = { location: "about:blank" };
  const open = vi.fn().mockReturnValue(w);
  vi.stubGlobal("open", open);
  render(<ExportBar jobId="5" />);
  await expandLayoutFormats();
  await userEvent.click(screen.getByTestId("btn-export-docx-layout"));
  expect(api.exportJob).toHaveBeenCalledWith("5", "docx-layout");
  await waitFor(() => expect(w.location).toBe("https://r2/exports/5/docx-layout"));
});

it("md-layout button renders and calls exportJob with md-layout (D5)", async () => {
  vi.mocked(api.exportJob).mockResolvedValue({ url: "https://r2/exports/5/md-layout" });
  const w = { location: "about:blank" };
  const open = vi.fn().mockReturnValue(w);
  vi.stubGlobal("open", open);
  render(<ExportBar jobId="5" />);
  await expandLayoutFormats();
  await userEvent.click(screen.getByTestId("btn-export-md-layout"));
  expect(api.exportJob).toHaveBeenCalledWith("5", "md-layout");
  await waitFor(() => expect(w.location).toBe("https://r2/exports/5/md-layout"));
});

it("shows ApiError detail when export fails", async () => {
  vi.mocked(api.exportJob).mockRejectedValue(new ApiError("Xuất file thất bại."));
  render(<ExportBar jobId="5" />);
  await expandLayoutFormats();
  await userEvent.click(screen.getByTestId("btn-export-docx-layout"));
  expect(await screen.findByTestId("export-error")).toHaveTextContent(
    "Xuất file thất bại.",
  );
});


/** Lane I Task 5: chỉ còn nhóm "Layout"; text formats KHÔNG còn trong ExportBar. */
it("renders nhóm 'Layout' + không còn text download buttons", async () => {
  render(<ExportBar jobId="5" />);
  const layoutGroup = screen.getByRole("button", { name: "Layout" });
  expect(layoutGroup).toHaveAttribute("aria-expanded", "false");
  for (const fmt of ["md", "html", "docx", "pdf"]) {
    expect(screen.queryByTestId(`export-${fmt}`)).not.toBeInTheDocument();
  }
  await userEvent.click(layoutGroup);
  expect(screen.getByTestId("btn-export-md-layout")).toBeVisible();
  expect(screen.getByTestId("btn-export-docx-layout")).toBeVisible();
});

it("disables only in-flight formats under concurrent clicks", async () => {
  const resolvers: Array<(v: { url: string }) => void> = [];
  vi.mocked(api.exportJob).mockImplementation(
    () => new Promise((res) => resolvers.push(res)),
  );
  render(<ExportBar jobId="5" />);
  await expandLayoutFormats();
  const mdLayout = screen.getByTestId("btn-export-md-layout");
  const docxLayout = screen.getByTestId("btn-export-docx-layout");
  await userEvent.click(mdLayout);
  await userEvent.click(docxLayout);
  expect(mdLayout).toBeDisabled();
  expect(docxLayout).toBeDisabled();
  resolvers[0]({ url: "https://r2/exports/5/md-layout" });
  await waitFor(() => expect(mdLayout).not.toBeDisabled());
  expect(docxLayout).toBeDisabled();
  resolvers[1]({ url: "https://r2/exports/5/docx-layout" });
  await waitFor(() => expect(docxLayout).not.toBeDisabled());
});
