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

  it("401 on non-auth path redirects to /signin and still throws ApiError", async () => {
    const assign = stubLocationAssign();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "Phiên đăng nhập hết hạn." }), { status: 401 }),
      ),
    );
    await expect(api.listJobs()).rejects.toThrow("Phiên đăng nhập hết hạn.");
    expect(assign).toHaveBeenCalledWith("/signin");
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

  // Plan M (M2): md-layout source save — PUT → 204 (no body) phải không ném.
  it("putMdLayoutContent sends PUT md-layout/content and accepts 204", async () => {
    const spy = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", spy);
    await expect(api.putMdLayoutContent(5, "# B")).resolves.toBeUndefined();
    const [url, opts] = spy.mock.calls[0];
    expect(url).toBe("/api/jobs/5/export/md-layout/content");
    expect(opts.method).toBe("PUT");
    expect(opts.headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(opts.body)).toEqual({ markdown: "# B" });
  });

  it("putLayoutStyle sends PUT layout-style with {style} body", async () => {
    const spy = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", spy);
    await expect(api.putLayoutStyle(5, { align: "center" })).resolves.toBeUndefined();
    const [url, opts] = spy.mock.calls[0];
    expect(url).toBe("/api/jobs/5/layout-style");
    expect(opts.method).toBe("PUT");
    expect(JSON.parse(opts.body)).toEqual({ style: { align: "center" } });
  });

  // Plan proofread: gợi ý sửa lỗi OCR.
  it("getSuggestions GETs /api/jobs/{id}/suggestions and returns array", async () => {
    const spy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([{ id: 1, page_index: 0, start: 0, end: 5, original: "a", suggestion: "b", reason: "r", status: "pending" }]), { status: 200 }),
    );
    vi.stubGlobal("fetch", spy);
    const items = await api.getSuggestions(5);
    expect(items).toHaveLength(1);
    expect(items[0].original).toBe("a");
    const [url, opts] = spy.mock.calls[0];
    expect(url).toBe("/api/jobs/5/suggestions");
    expect(opts.method).toBe("GET");
  });

  it("acceptSuggestion POSTs accept and returns {status}", async () => {
    const spy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "accepted" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", spy);
    await expect(api.acceptSuggestion(5, 7)).resolves.toEqual({ status: "accepted" });
    const [url, opts] = spy.mock.calls[0];
    expect(url).toBe("/api/jobs/5/suggestions/7/accept");
    expect(opts.method).toBe("POST");
  });

  it("rejectSuggestion POSTs reject and returns {status}", async () => {
    const spy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "rejected" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", spy);
    await expect(api.rejectSuggestion(5, 7)).resolves.toEqual({ status: "rejected" });
    const [url, opts] = spy.mock.calls[0];
    expect(url).toBe("/api/jobs/5/suggestions/7/reject");
    expect(opts.method).toBe("POST");
  });

  it("runProofread POSTs proofread and returns {count}", async () => {
    const spy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ count: 3 }), { status: 200 }),
    );
    vi.stubGlobal("fetch", spy);
    await expect(api.runProofread(5)).resolves.toEqual({ count: 3 });
    const [url, opts] = spy.mock.calls[0];
    expect(url).toBe("/api/jobs/5/proofread");
    expect(opts.method).toBe("POST");
  });

  // --- Phase 2 (spec Sub-system B): extraction save + sync ---

  it("getExtraction GETs text + text_version", async () => {
    const spy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ text: "Xin chào", text_version: 3 }), { status: 200 }),
    );
    vi.stubGlobal("fetch", spy);
    await expect(api.getExtraction(5)).resolves.toEqual({ text: "Xin chào", text_version: 3 });
    const [url, opts] = spy.mock.calls[0];
    expect(url).toBe("/api/jobs/5/extraction");
    expect(opts.method).toBe("GET");
  });

  it("saveExtraction POSTs text + phrase pair + expected_text_version", async () => {
    const spy = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ synced: { md: true, docx: false }, needs_render: ["docx-layout"], text_version: 4 }),
        { status: 200 },
      ),
    );
    vi.stubGlobal("fetch", spy);
    const result = await api.saveExtraction(5, {
      text: "Xin cháo",
      old_phrase: "chao",
      new_phrase: "chào",
      expected_text_version: 3,
    });
    expect(result).toEqual({ synced: { md: true, docx: false }, needs_render: ["docx-layout"], text_version: 4 });
    const [url, opts] = spy.mock.calls[0];
    expect(url).toBe("/api/jobs/5/extraction");
    expect(opts.method).toBe("POST");
    expect(JSON.parse(opts.body)).toEqual({
      text: "Xin cháo",
      old_phrase: "chao",
      new_phrase: "chào",
      expected_text_version: 3,
    });
  });

  it("saveExtraction sends force flag when given (detached 409 retry)", async () => {
    const spy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ synced: { md: true, docx: true }, needs_render: [], text_version: 4 }), { status: 200 }),
    );
    vi.stubGlobal("fetch", spy);
    await api.saveExtraction(5, { text: "t", expected_text_version: 3, force: true });
    expect(JSON.parse(spy.mock.calls[0][1].body).force).toBe(true);
  });

  it("listVersions GETs versions filtered by kind", async () => {
    const items = [{ id: 1, kind: "text", version: 2, based_on_text_version: 2, detached: false, created_at: "2026-10-10T00:00:00Z" }];
    const spy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items }), { status: 200 }),
    );
    vi.stubGlobal("fetch", spy);
    await expect(api.listVersions(5, "text")).resolves.toEqual({ items });
    const [url, opts] = spy.mock.calls[0];
    expect(url).toBe("/api/jobs/5/versions?kind=text");
    expect(opts.method).toBe("GET");
  });

  it("restoreVersion POSTs restore (204 no body)", async () => {
    const spy = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", spy);
    await expect(api.restoreVersion(5, 9)).resolves.toBeUndefined();
    const [url, opts] = spy.mock.calls[0];
    expect(url).toBe("/api/jobs/5/versions/9/restore");
    expect(opts.method).toBe("POST");
  });
});
