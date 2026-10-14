import { describe, expect, it } from "vitest";
import { ApiError } from "../../src/api/client";
import { mapApiError } from "../../src/lib/errors";

describe("mapApiError (R59)", () => {
  it("ApiError → e.detail verbatim", () => {
    expect(mapApiError(new ApiError("Đã đạt giới hạn upload hôm nay."))).toBe(
      "Đã đạt giới hạn upload hôm nay.",
    );
  });

  it("TypeError / 'fetch failed' → network message", () => {
    const net = "Cannot reach the server. Check that it is running.";
    expect(mapApiError(new TypeError("fetch failed"))).toBe(net);
    expect(mapApiError(new Error("TypeError: fetch failed"))).toBe(net);
  });

  it("generic fallback → Error.message or String(e)", () => {
    expect(mapApiError(new Error("boom"))).toBe("boom");
    expect(mapApiError(42)).toBe("42");
    expect(mapApiError("plain")).toBe("plain");
  });
});
