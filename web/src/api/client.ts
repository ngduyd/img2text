import type { AdminStatsDay, Job, JobsPage, RegionPatchOut, User, AdminSettings, AdminSettingsPut, LayoutStyle, Suggestion } from "./types";

/** Thrown for any non-2xx response; `detail` mirrors FastAPI {detail} bodies. */
export class ApiError extends Error {
  detail: string;

  constructor(detail: string) {
    super(detail);
    this.name = "ApiError";
    this.detail = detail;
  }
}

interface RequestOptions {
  method?: string;
  /** Plain object → JSON body + Content-Type; FormData → multipart (browser sets boundary). */
  body?: unknown;
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {};
  let body: BodyInit | undefined;
  if (opts.body instanceof FormData) {
    body = opts.body;
  } else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, {
    method: opts.method ?? "GET",
    credentials: "include",
    headers,
    ...(body !== undefined ? { body } : {}),
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const data = (await res.json()) as { detail?: string } | null;
      if (data && typeof data.detail === "string") detail = data.detail;
    } catch {
      // non-JSON error body → keep generic detail
    }
    // R36: non-auth 401 → session lost, bounce to login. Auth endpoints
    // (login/signup/forgot/reset/refresh/logout) handle their own failures.
    if (res.status === 401 && !path.startsWith("/api/auth/")) {
      window.location.assign("/signin");
    }
    throw new ApiError(detail);
  }
  // 204 = no body (Plan M PUTs) — res.json() would throw on empty payload.
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  register: (email: string, password: string) =>
    request<User>("/api/auth/register", { method: "POST", body: { email, password } }),
  login: (email: string, password: string) =>
    request<User>("/api/auth/login", { method: "POST", body: { email, password } }),
  logout: () => request<unknown>("/api/auth/logout", { method: "POST" }),
  me: () => request<User>("/api/auth/me"),
  updateProfile: (body: { current_password: string; email?: string; new_password?: string }) =>
    request<User>("/api/auth/profile", { method: "PATCH", body }),
  refresh: () => request<unknown>("/api/auth/refresh", { method: "POST" }),
  forgotEmail: (email: string) =>
    request<unknown>("/api/auth/password/forgot", { method: "POST", body: { email } }),
  resetPassword: (token: string, password: string) =>
    request<unknown>("/api/auth/password/reset", { method: "POST", body: { token, password } }),
  // Phase 4: server-side pagination (page default 1, page_size default 10 max 100).
  listJobs: (page = 1, page_size = 10) =>
    request<JobsPage>(`/api/jobs?page=${page}&page_size=${page_size}`),
  getJob: (id: number | string) => request<Job>(`/api/jobs/${id}`),
  // Blob has no name — `filename` supplies the multipart filename (e.g. cropped JPEG).
  uploadJob: (
    file: File | Blob,
    opts?: { filename?: string; preprocess?: object; output_format?: string; mode?: string },
  ) => {
    const form = new FormData();
    if (opts?.filename !== undefined) form.append("file", file, opts.filename);
    else form.append("file", file);
    // R56: optional multipart field "preprocess" (JSON string) — server validates shape.
    if (opts?.preprocess !== undefined) form.append("preprocess", JSON.stringify(opts.preprocess));
    // Plan D4: export format chosen at upload ("md" | "docx"); server defaults to md.
    if (opts?.output_format !== undefined) form.append("output_format", opts.output_format);
    // Phase 5: "layout" | "extract_only" — server defaults to layout when absent.
    if (opts?.mode !== undefined) form.append("mode", opts.mode);
    return request<{ id: number; status: string }>("/api/jobs", { method: "POST", body: form });
  },
  retryJob: (id: number | string) =>
    request<void>(`/api/jobs/${id}/retry`, { method: "POST" }),
  // Phase 4: bulk retry — per-job settle; một job fail KHÔNG abort cả batch.
  retryJobs: async (ids: Array<number | string>): Promise<{ ok: number; errors: string[] }> => {
    const results = await Promise.allSettled(ids.map((id) => api.retryJob(id)));
    const errors = results.flatMap((r) =>
      r.status === "rejected"
        ? [r.reason instanceof Error ? r.reason.message : String(r.reason)]
        : [],
    );
    return { ok: results.length - errors.length, errors };
  },
  retryLayout: (id: number | string) =>
    request<{ md: boolean; docx: boolean }>(`/api/jobs/${id}/retry-layout`, { method: "POST" }),
  getJobFile: (id: number | string) => request<{ url: string }>(`/api/jobs/${id}/file`),
  patchContent: (id: number | string, markdown: string) =>
    request<unknown>(`/api/jobs/${id}/content`, { method: "PATCH", body: { markdown } }),
  // Plan M (M2): nguồn md-layout (artifact) — KHÁC patchContent (VLM content).
  putMdLayoutContent: (id: number | string, markdown: string) =>
    request<unknown>(`/api/jobs/${id}/export/md-layout/content`, {
      method: "PUT",
      body: { markdown },
    }),
  // Plan M (M1): word style overrides (null = xoá override).
  putLayoutStyle: (id: number | string, style: LayoutStyle | null) =>
    request<unknown>(`/api/jobs/${id}/layout-style`, { method: "PUT", body: { style } }),
  // Plan M3 (server lane): PUT docx.html (nội dung word đã sửa) — 204.
  putDocxHtml: (id: number | string, html: string) =>
    request<unknown>(`/api/jobs/${id}/export/docx-layout/html`, {
      method: "PUT",
      body: { html },
    }),
  // Plan M3: đọc docx.html cache (200 text/html); chưa lưu → 404 → null (fallback mammoth).
  getDocxHtml: async (id: number | string): Promise<string | null> => {
    const path = `/api/jobs/${id}/export/docx.html/download`;
    const res = await fetch(path, { credentials: "include" });
    if (res.status === 404) return null;
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const data = (await res.json()) as { detail?: string } | null;
        if (data && typeof data.detail === "string") detail = data.detail;
      } catch {
        // non-JSON error body → keep generic detail
      }
      if (res.status === 401) window.location.assign("/signin");
      throw new ApiError(detail);
    }
    return await res.text();
  },
  exportJob: (id: number | string, fmt: string) =>
    request<{ url: string }>(`/api/jobs/${id}/export`, { method: "POST", body: { fmt } }),
  // Task 5: same-origin blob download of a cached export (presign window.open not usable for iframe srcdoc).
  downloadExport: async (id: number | string, fmt: string): Promise<Blob> => {
    const path = `/api/jobs/${id}/export/${fmt}/download`;
    const res = await fetch(path, { credentials: "include" });
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const data = (await res.json()) as { detail?: string } | null;
        if (data && typeof data.detail === "string") detail = data.detail;
      } catch {
        // non-JSON error body → keep generic detail
      }
      if (res.status === 401) window.location.assign("/signin");
      throw new ApiError(detail);
    }
    return await res.blob();
  },
  // Plan V (V2): same-origin blob download of the ORIGINAL file (presigned
  // localhost:4566 unreachable via VSCode port-forward). Pattern: downloadExport.
  downloadJobFile: async (id: number | string): Promise<Blob> => {
    const path = `/api/jobs/${id}/file/download`;
    const res = await fetch(path, { credentials: "include" });
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const data = (await res.json()) as { detail?: string } | null;
        if (data && typeof data.detail === "string") detail = data.detail;
      } catch {
        // non-JSON error body → keep generic detail
      }
      if (res.status === 401) window.location.assign("/signin");
      throw new ApiError(detail);
    }
    return await res.blob();
  },
  getCropUrl: (jobId: number | string, rid: string) =>
    request<{ url: string }>(`/api/jobs/${jobId}/regions/${rid}/crop`),
  patchRegion: (jobId: number | string, rid: string, text: string) =>
    request<RegionPatchOut>(`/api/jobs/${jobId}/regions/${rid}`, {
      method: "PATCH",
      body: { text },
    }),
  adminListUsers: (page: number) =>
    request<{ items: User[]; total: number }>(`/api/admin/users?page=${page}`),
  adminPatchUser: (id: number | string, body: { ocr_enabled: boolean }) =>
    request<User>(`/api/admin/users/${id}`, { method: "PATCH", body }),
  adminStats: (from: string, to: string) =>
    request<{ days: AdminStatsDay[] }>(`/api/admin/stats?from=${from}&to=${to}`),
  adminLogs: (filters: { status_class?: string; ip?: string; limit?: number }) => {
    const q = new URLSearchParams();
    if (filters.status_class !== undefined) q.set("status_class", filters.status_class);
    if (filters.ip !== undefined) q.set("ip", filters.ip);
    if (filters.limit !== undefined) q.set("limit", String(filters.limit));
    return request<{ items: Record<string, unknown>[] }>(`/api/admin/logs?${q.toString()}`);
  },
  adminLogsTail: (lines: number) =>
    request<{ lines: string[] }>(`/api/admin/logs/tail?lines=${lines}`),
  // Plan S: runtime settings (scheduler/kaggle live override, no restart)
  getAdminSettings: () => request<AdminSettings>("/api/admin/settings"),
  putAdminSettings: (body: AdminSettingsPut) =>
    request<AdminSettings>("/api/admin/settings", { method: "PUT", body }),
  // Plan proofread: gợi ý sửa lỗi OCR (client tự replace + save, server chỉ lưu status).
  getSuggestions: (id: number | string) =>
    request<Suggestion[]>(`/api/jobs/${id}/suggestions`),
  acceptSuggestion: (id: number | string, sid: number) =>
    request<{ status: string }>(`/api/jobs/${id}/suggestions/${sid}/accept`, { method: "POST" }),
  rejectSuggestion: (id: number | string, sid: number) =>
    request<{ status: string }>(`/api/jobs/${id}/suggestions/${sid}/reject`, { method: "POST" }),
  runProofread: (id: number | string) =>
    request<{ count: number }>(`/api/jobs/${id}/proofread`, { method: "POST" }),
};
