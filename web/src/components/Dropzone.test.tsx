import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createEvent, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../api/client";
import type { User } from "../api/types";
import Dropzone from "./Dropzone";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      me: vi.fn(),
      uploadJob: vi.fn(),
    },
  };
});

function renderDropzone(onUploaded = vi.fn()) {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <Dropzone onUploaded={onUploaded} />
    </QueryClientProvider>,
  );
  return onUploaded;
}

beforeEach(() => {
  vi.clearAllMocks();
});

it("dragover preventDefault and drop triggers uploadJob", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: true } as User);
  vi.mocked(api.uploadJob).mockResolvedValue({ id: 42, status: "queued" });
  const onUploaded = renderDropzone();
  await screen.findByTestId("btn-upload");
  const file = new File(["x"], "a.jpg", { type: "image/jpeg" });
  const dz = screen.getByTestId("dropzone");
  const over = createEvent.dragOver(dz, { cancelable: true, dataTransfer: { files: [] } });
  fireEvent(dz, over);
  expect(over.defaultPrevented).toBe(true);
  fireEvent.drop(dz, { dataTransfer: { files: [file] } });
  await waitFor(() => expect(api.uploadJob).toHaveBeenCalledWith(file));
  await waitFor(() => expect(onUploaded).toHaveBeenCalledWith({ id: 42, status: "queued" }));
});

it("drop uploads nothing when ocr not enabled", async () => {
  vi.mocked(api.me).mockResolvedValue({ id: 1, role: "user", ocr_enabled: false } as User);
  renderDropzone();
  await screen.findByTestId("banner-no-access");
  const file = new File(["x"], "a.jpg", { type: "image/jpeg" });
  fireEvent.drop(screen.getByTestId("dropzone"), { dataTransfer: { files: [file] } });
  expect(api.uploadJob).not.toHaveBeenCalled();
});
