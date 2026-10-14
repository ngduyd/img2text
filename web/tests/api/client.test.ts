import { describe, it, expect, vi } from "vitest";
import { api } from "../../src/api/client";

// R30: pdfjs mocked at module boundary — uploadJob counts pages via loadPdf.
vi.mock("../../src/lib/pdfjs", () => ({
  loadPdf: vi.fn(async () => ({ numPages: 3, getPage: vi.fn() })),
}));

function stubLocationAssign() {
  const assign = vi.fn();
  vi.stubGlobal("location", { assign }); // jsdom location is not spy-able; documented approach
  return assign;
}

const PRESIGN = {
  storage_key: `uploads/${"ab".repeat(32)}.jpg`,
  url: "https://r2.example/bucket/uploads/ab.jpg",
  max_bytes: 52428800,
};

interface XhrState {
  url: string;
  method: string;
  body: unknown;
  headers: Record<string, string>;
  progress: number[];
  fireProgress: (loaded: number, total: number) => void;
  finish: (status?: number) => void;
  error: () => void;
}

/** Fake XMLHttpRequest: captures the PUT + ArrayBuffer body, manual progress/load control. */
function stubXHR(autoFinish = true): XhrState[] {
  const calls: XhrState[] = [];
  class FakeXHR {
    upload = { onprogress: null as ((e: ProgressEvent) => void) | null };
    status = 200;
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    private url = "";
    private method = "";
    private headers: Record<string, string> = {};
    setRequestHeader(k: string, v: string) {
      this.headers[k] = v;
    }
    open(method: string, url: string) {
      this.method = method;
      this.url = url;
    }
    send(body: unknown) {
      const state: XhrState = {
        url: this.url,
        method: this.method,
        body,
        headers: this.headers,
        progress: [],
        fireProgress: (loaded, total) => {
          state.progress.push(Math.round((loaded / total) * 100));
          this.upload.onprogress?.({ loaded, total, lengthComputable: true } as ProgressEvent);
        },
        finish: (status) => {
          if (status !== undefined) this.status = status;
          this.onload?.();
        },
        error: () => this.onerror?.(),
      };
      calls.push(state);
      if (autoFinish) queueMicrotask(() => this.onload?.());
    }
  }
  vi.stubGlobal("XMLHttpRequest", FakeXHR);
  return calls;
}

/** fetch router: URL → JSON body (200). */
function stubFetchRoutes(routes: Record<string, unknown>) {
  const spy = vi.fn(async (url: string, _opts?: { method?: string; body?: string }) =>
    new Response(JSON.stringify(routes[String(url)] ?? {}), { status: 200 }),
  );
  vi.stubGlobal("fetch", spy);
  return spy;
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

  it("uploadJob presigns, PUTs the ArrayBuffer straight to storage, then creates metadata-only", async () => {
    const xhrs = stubXHR();
    const spy = stubFetchRoutes({ "/api/jobs/presign": PRESIGN, "/api/jobs": { id: 1, status: "queued" } });
    const file = new File(["x"], "a.jpg", { type: "image/jpeg" });
    await api.uploadJob(file, {
      output_format: "docx",
      mode: "extract_only",
      preprocess: { pages: [1, 3], rotate: { "2": 90 } },
    });
    const presignCall = spy.mock.calls.find(([url]) => String(url) === "/api/jobs/presign");
    // content-addressed key: client-computed sha256 ("x")
    expect(JSON.parse(String(presignCall?.[1]?.body))).toEqual({
      filename: "a.jpg",
      content_type: "image/jpeg",
      size_bytes: 1,
      sha256: "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881",
      output_format: "docx",
      mode: "extract_only",
    });
    // PUT ArrayBuffer → storage (KHÔNG qua backend; KHÔNG Content-Type
    // header — browser không tự thêm cho ArrayBuffer, tránh signature mismatch).
    // Red-green: fail ngay khi code set bất kỳ Content-Type nào (kể cả casing khác).
    expect(xhrs).toHaveLength(1);
    expect(xhrs[0].method).toBe("PUT");
    expect(xhrs[0].url).toBe(PRESIGN.url);
    expect(xhrs[0].body).toBeInstanceOf(ArrayBuffer);
    expect((xhrs[0].body as ArrayBuffer).byteLength).toBe(1);
    for (const xhr of xhrs) {
      expect(Object.keys(xhr.headers).filter((k) => k.toLowerCase() === "content-type")).toEqual([]);
    }
    // create = metadata-only
    const createCall = spy.mock.calls.find(
      ([url, opts]) => String(url) === "/api/jobs" && opts?.method === "POST",
    );
    expect(JSON.parse(String(createCall?.[1]?.body))).toEqual({
      storage_key: PRESIGN.storage_key,
      page_count: 1,
      filename: "a.jpg",
      output_format: "docx",
      mode: "extract_only",
      preprocess: { pages: [1, 3], rotate: { "2": 90 } },
    });
  });

  /** Lane B Task 5: ảnh phone → TYPE_BY_EXT heic/heif/avif (server presign validate declared). */
  it.each([
    ["x.heif", "image/heif"],
    ["x.avif", "image/avif"],
    ["x.heic", "image/heic"],
  ])("uploadJob %s → presign content_type %s", async (filename, content_type) => {
    stubXHR();
    const spy = stubFetchRoutes({ "/api/jobs/presign": PRESIGN, "/api/jobs": { id: 1, status: "queued" } });
    await api.uploadJob(new File(["ftyp"], filename, { type: content_type }), { filename });
    const presignBody = JSON.parse(
      String(spy.mock.calls.find(([url]) => String(url) === "/api/jobs/presign")?.[1]?.body),
    );
    expect(presignBody.content_type).toBe(content_type);
    expect(presignBody.filename).toBe(filename);
  });

  it("uploadJob omits preprocess/output_format/mode when opts absent", async () => {
    stubXHR();
    const spy = stubFetchRoutes({ "/api/jobs/presign": PRESIGN, "/api/jobs": { id: 1, status: "queued" } });
    await api.uploadJob(new File(["x"], "a.jpg", { type: "image/jpeg" }));
    const presignBody = JSON.parse(
      String(spy.mock.calls.find(([url]) => String(url) === "/api/jobs/presign")?.[1]?.body),
    );
    expect(presignBody).not.toHaveProperty("output_format");
    expect(presignBody).not.toHaveProperty("mode");
    const createCall = spy.mock.calls.find(
      ([url, opts]) => String(url) === "/api/jobs" && opts?.method === "POST",
    );
    expect(JSON.parse(String(createCall?.[1]?.body))).toEqual({
      storage_key: PRESIGN.storage_key,
      page_count: 1,
      filename: "a.jpg",
    });
  });

  it("uploadJob reports upload progress percent + phase transitions", async () => {
    const xhrs = stubXHR();
    stubFetchRoutes({ "/api/jobs/presign": PRESIGN, "/api/jobs": { id: 1, status: "queued" } });
    const phases: string[] = [];
    const percents: number[] = [];
    const done = api.uploadJob(new File(["x"], "a.jpg", { type: "image/jpeg" }), {
      onPhase: (p) => phases.push(p),
      onProgress: (p) => percents.push(p),
    });
    // onprogress fires DURING the XHR upload → percent updates
    await vi.waitFor(() => expect(xhrs).toHaveLength(1));
    xhrs[0].fireProgress(40, 100);
    xhrs[0].fireProgress(100, 100);
    xhrs[0].finish();
    await done;
    expect(percents).toEqual([40, 100]);
    expect(phases).toEqual(["uploading", "counting"]);
  });

  it("uploadJob counts PDF pages with pdf.js AFTER the upload", async () => {
    stubXHR();
    const spy = stubFetchRoutes({ "/api/jobs/presign": PRESIGN, "/api/jobs": { id: 1, status: "queued" } });
    await api.uploadJob(new File(["%PDF"], "a.pdf", { type: "application/pdf" }));
    const createCall = spy.mock.calls.find(
      ([url, opts]) => String(url) === "/api/jobs" && opts?.method === "POST",
    );
    expect(JSON.parse(String(createCall?.[1]?.body)).page_count).toBe(3); // loadPdf mock numPages
  });

  it("uploadJob rejects on non-2xx storage PUT", async () => {
    const xhrs = stubXHR(false);
    stubFetchRoutes({ "/api/jobs/presign": PRESIGN });
    const done = api.uploadJob(new File(["x"], "a.jpg", { type: "image/jpeg" }));
    await vi.waitFor(() => expect(xhrs).toHaveLength(1));
    xhrs[0].finish(403);
    await expect(done).rejects.toThrow("HTTP 403");
  });

  it("uploadJob rejects with detail message on network error", async () => {
    const xhrs = stubXHR(false);
    stubFetchRoutes({ "/api/jobs/presign": PRESIGN });
    const done = api.uploadJob(new File(["x"], "a.jpg", { type: "image/jpeg" }));
    await vi.waitFor(() => expect(xhrs).toHaveLength(1));
    xhrs[0].error();
    await expect(done).rejects.toThrow("File upload failed.");
  });

  it("uploadJob accepts Blob + filename (cropped JPEG — filename chỉ tới presign metadata)", async () => {
    const xhrs = stubXHR();
    const spy = stubFetchRoutes({ "/api/jobs/presign": PRESIGN, "/api/jobs": { id: 1, status: "queued" } });
    const blob = new Blob(["x"], { type: "image/jpeg" });
    await api.uploadJob(blob, { filename: "photo-crop.jpg" });
    const presignCall = spy.mock.calls.find(([url]) => String(url) === "/api/jobs/presign");
    expect(JSON.parse(String(presignCall?.[1]?.body)).filename).toBe("photo-crop.jpg");
    expect(xhrs[0].body).toBeInstanceOf(ArrayBuffer);
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

  it("listJobs appends page + page_size params", async () => {
    const spy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], total: 0, page: 2, page_size: 20 }), { status: 200 }),
    );
    vi.stubGlobal("fetch", spy);
    await api.listJobs(2, 20);
    const [url] = spy.mock.calls[0];
    expect(url).toBe("/api/jobs?page=2&page_size=20");
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

describe("listJobs filters (spec #3)", () => {
  it("appends q/sort/status params", async () => {
    const spy = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], total: 0 }), { status: 200 }),
    );
    vi.stubGlobal("fetch", spy);
    await api.listJobs(1, 10, { q: "sach", sort: "oldest", status: "done" });
    const [url] = spy.mock.calls[0];
    expect(url).toBe("/api/jobs?page=1&page_size=10&q=sach&sort=oldest&status=done");
  });
});
