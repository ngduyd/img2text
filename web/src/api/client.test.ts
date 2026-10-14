import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, request } from "./client";

/** Lane M3 P1b: server 409 detached gửi detail dict {code, detail}. */
describe("request — detached 409 detail dict", () => {
  afterEach(() => vi.restoreAllMocks());

  it("unwraps {code,detail} dict → err.code === \"detached\"", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: { code: "detached", detail: "Layout có chỉnh tay. Đồng bộ sẽ ghi đè." },
        }),
        { status: 409 },
      ),
    );
    const err = await request("/api/jobs/1/extraction", { method: "POST" }).catch(
      (e) => e,
    );
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe("detached");
    expect((err as ApiError).detail).toBe("Layout có chỉnh tay. Đồng bộ sẽ ghi đè.");
  });

  it("plain string detail (server cũ) → code undefined, detail giữ nguyên", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Nội dung trống." }), { status: 422 }),
    );
    const err = await request("/api/jobs/1/extraction", { method: "POST" }).catch(
      (e) => e,
    );
    expect((err as ApiError).code).toBeUndefined();
    expect((err as ApiError).detail).toBe("Nội dung trống.");
  });
});
