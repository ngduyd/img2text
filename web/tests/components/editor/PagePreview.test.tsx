import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import PagePreview from "../../../src/components/editor/PagePreview";

const preview = vi.fn();
vi.mock("pagedjs", () => ({ Previewer: class { preview = preview; } }));

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  preview.mockReset();
});
afterEach(() => vi.useRealTimers());

it("D7: debounce 500ms — chỉ gọi paged.js 1 lần cho lần sửa cuối", async () => {
  preview.mockResolvedValue({ total: 2 });
  const { rerender } = render(<PagePreview html="<p>a</p>" />);
  rerender(<PagePreview html="<p>ab</p>" />);
  rerender(<PagePreview html="<p>abc</p>" />);
  expect(preview).not.toHaveBeenCalled();
  await vi.advanceTimersByTimeAsync(600);
  await waitFor(() => expect(preview).toHaveBeenCalledTimes(1));
  expect(preview.mock.calls[0][0]).toBe("<p>abc</p>");
  await waitFor(() => expect(screen.getByTestId("page-count")).toHaveTextContent("2"));
});

it("paged.js lỗi (jsdom) → fallback HTML thường, không vỡ trang soạn", async () => {
  preview.mockRejectedValue(new Error("no layout engine"));
  render(<PagePreview html="<p>fallback</p>" />);
  await vi.advanceTimersByTimeAsync(600);
  await waitFor(() =>
    expect(screen.getByTestId("page-preview")).toHaveTextContent("fallback"),
  );
  expect(screen.getByTestId("page-count")).toHaveTextContent("–");
});
