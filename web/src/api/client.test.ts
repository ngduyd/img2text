import { describe, it, expect, vi } from "vitest";
import { api } from "./client";

function stubLocationAssign() {
  const assign = vi.fn();
  vi.stubGlobal("location", { assign }); // jsdom location is not spy-able; documented approach
  return assign;
}

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

  it("401 on non-auth path redirects to /login and still throws ApiError", async () => {
    const assign = stubLocationAssign();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Phiên đăng nhập hết hạn." }), { status: 401 }),
      ),
    );
    await expect(api.listJobs()).rejects.toThrow("Phiên đăng nhập hết hạn.");
    expect(assign).toHaveBeenCalledWith("/login");
  });

  it("401 on /api/auth/login does NOT redirect", async () => {
    const assign = stubLocationAssign();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Sai mật khẩu." }), { status: 401 }),
      ),
    );
    await expect(api.login("u@x.io", "bad")).rejects.toThrow("Sai mật khẩu.");
    expect(assign).not.toHaveBeenCalled();
  });
});
