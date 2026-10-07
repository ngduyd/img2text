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

it("four export buttons exist and call api with fmt", async () => {
  vi.mocked(api.exportJob).mockResolvedValue({ url: "https://r2/exports/5/docx" });
  const w = { location: "about:blank" };
  const open = vi.fn().mockReturnValue(w);
  vi.stubGlobal("open", open);
  render(<ExportBar jobId="5" />);
  for (const fmt of ["md", "html", "docx", "pdf"]) {
    expect(screen.getByTestId(`export-${fmt}`)).toBeInTheDocument();
  }
  await userEvent.click(screen.getByTestId("export-docx"));
  expect(api.exportJob).toHaveBeenCalledWith("5", "docx");
  await waitFor(() => expect(w.location).toBe("https://r2/exports/5/docx"));
});

it("docx-layout button renders and calls exportJob with docx-layout (D4 review)", async () => {
  vi.mocked(api.exportJob).mockResolvedValue({ url: "https://r2/exports/5/docx-layout" });
  const w = { location: "about:blank" };
  const open = vi.fn().mockReturnValue(w);
  vi.stubGlobal("open", open);
  render(<ExportBar jobId="5" />);
  await userEvent.click(screen.getByTestId("btn-export-docx-layout"));
  expect(api.exportJob).toHaveBeenCalledWith("5", "docx-layout");
  await waitFor(() => expect(w.location).toBe("https://r2/exports/5/docx-layout"));
});

it("shows ApiError detail when export fails", async () => {
  vi.mocked(api.exportJob).mockRejectedValue(new ApiError("Xuất file thất bại."));
  render(<ExportBar jobId="5" />);
  await userEvent.click(screen.getByTestId("export-pdf"));
  expect(await screen.findByTestId("export-error")).toHaveTextContent(
    "Xuất file thất bại.",
  );
});

it("disables only in-flight formats under concurrent clicks", async () => {
  const resolvers: Array<(v: { url: string }) => void> = [];
  vi.mocked(api.exportJob).mockImplementation(
    () => new Promise((res) => resolvers.push(res)),
  );
  render(<ExportBar jobId="5" />);
  const md = screen.getByTestId("export-md");
  const html = screen.getByTestId("export-html");
  await userEvent.click(md);
  await userEvent.click(html);
  expect(md).toBeDisabled();
  expect(html).toBeDisabled();
  resolvers[0]({ url: "https://r2/exports/5/md" });
  await waitFor(() => expect(md).not.toBeDisabled());
  expect(html).toBeDisabled();
  resolvers[1]({ url: "https://r2/exports/5/html" });
  await waitFor(() => expect(html).not.toBeDisabled());
});
