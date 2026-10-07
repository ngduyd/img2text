import { describe, it, expect, vi } from "vitest";
import { api } from "../../src/api/client";

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

  it("uploadJob appends preprocess JSON field when opts.preprocess present", async () => {
    const spy = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 1, status: "queued" }), { status: 200 }));
    vi.stubGlobal("fetch", spy);
    const file = new File(["%PDF"], "a.pdf", { type: "application/pdf" });
    await api.uploadJob(file, { preprocess: { pages: [1, 3], rotate: { "2": 90 } } });
    const [, opts] = spy.mock.calls[0];
    const form = opts.body as FormData;
    expect(form.get("file")).toBe(file);
    expect(form.get("preprocess")).toBe(JSON.stringify({ pages: [1, 3], rotate: { "2": 90 } }));
  });

  it("uploadJob omits preprocess field when opts absent", async () => {
    const spy = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 1, status: "queued" }), { status: 200 }));
    vi.stubGlobal("fetch", spy);
    await api.uploadJob(new File(["x"], "a.jpg", { type: "image/jpeg" }));
    const [, opts] = spy.mock.calls[0];
    expect((opts.body as FormData).get("preprocess")).toBeNull();
  });

  it("uploadJob appends output_format field when opts.output_format present", async () => {
    const spy = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 1, status: "queued" }), { status: 200 }));
    vi.stubGlobal("fetch", spy);
    const file = new File(["x"], "a.jpg", { type: "image/jpeg" });
    await api.uploadJob(file, { output_format: "docx" });
    const [, opts] = spy.mock.calls[0];
    expect((opts.body as FormData).get("output_format")).toBe("docx");
  });

  it("uploadJob omits output_format field when opts absent", async () => {
    const spy = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 1, status: "queued" }), { status: 200 }));
    vi.stubGlobal("fetch", spy);
    await api.uploadJob(new File(["x"], "a.jpg", { type: "image/jpeg" }));
    const [, opts] = spy.mock.calls[0];
    expect((opts.body as FormData).get("output_format")).toBeNull();
  });

  it("uploadJob accepts Blob + filename (cropped JPEG multipart name)", async () => {
    const spy = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: 1, status: "queued" }), { status: 200 }));
    vi.stubGlobal("fetch", spy);
    const blob = new Blob(["x"], { type: "image/jpeg" });
    await api.uploadJob(blob, { filename: "photo-crop.jpg" });
    const [, opts] = spy.mock.calls[0];
    const entry = (opts.body as FormData).get("file") as File;
    expect(entry.name).toBe("photo-crop.jpg");
    expect(entry.type).toBe("image/jpeg");
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

  it("getJobFile GETs /api/jobs/{id}/file and returns {url}", async () => {
    const spy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ url: "https://signed.example/f" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", spy);
    await expect(api.getJobFile(9)).resolves.toEqual({ url: "https://signed.example/f" });
    const [url, opts] = spy.mock.calls[0];
    expect(url).toBe("/api/jobs/9/file");
    expect(opts.method).toBe("GET");
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
