import { describe, it, expect, vi } from "vitest";
import { api } from "./client";

describe("api client", () => {
  it("login sends credentials include and json body", async () => {
    const spy = vi.fn().mockResolvedValue(new Response(JSON.stringify({}), { status: 200 }));
    vi.stubGlobal("fetch", spy);
    await api.login("u@x.io", "secret123");
    const [url, opts] = spy.mock.calls[0];
    expect(url).toBe("/api/auth/login");
    expect(opts.credentials).toBe("include");
    expect(JSON.parse(opts.body)).toEqual({ email: "u@x.io", password: "secret123" });
  });

  it("throws ApiError with detail on 4xx", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Chưa được cấp quyền OCR." }), { status: 403 }),
      ),
    );
    await expect(api.uploadJob(new File([], "a.jpg"))).rejects.toThrow("Chưa được cấp quyền OCR.");
  });
});
