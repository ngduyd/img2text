import { beforeEach, expect, it, vi } from "vitest";
import { api } from "../../src/api/client";
import { clearJobBlobCache, getJobBlob } from "../../src/lib/blobCache";

vi.mock("../../src/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../src/api/client")>();
  return {
    ...actual,
    api: { ...actual.api, downloadJobFile: vi.fn() },
  };
});

beforeEach(() => {
  vi.clearAllMocks();
  clearJobBlobCache();
  vi.mocked(api.downloadJobFile).mockResolvedValue(new Blob(["x"]));
});

// P2-6 review r1: cap Map ≤ 4 — SPA session không tích blob vô hạn.
it("insert 5 → giữ 4, evict entry cũ nhất", async () => {
  for (const id of ["1", "2", "3", "4", "5"]) {
    await getJobBlob(id);
  }
  vi.mocked(api.downloadJobFile).mockClear();
  // "1" = cũ nhất → bị evict → fetch lại
  await getJobBlob("1");
  expect(api.downloadJobFile).toHaveBeenCalledTimes(1);
  expect(api.downloadJobFile).toHaveBeenCalledWith("1");
  // "5" = mới nhất → còn cache → không fetch lại
  await getJobBlob("5");
  expect(api.downloadJobFile).toHaveBeenCalledTimes(1);
});
