import type { AdminStatsDay, FeedbackItem, Job, JobsPage, QuotaPatch, RegionPatchOut, User, AdminSettings, AdminSettingsPut, LayoutStyle, Suggestion, Extraction, ExtractionSaveResult, DocumentVersion, WorkersResponse, StorageOverview } from "./types";
import { loadPdf } from "../lib/pdfjs";
import { translate } from "../i18n";

/** Thrown for any non-2xx response; `detail` mirrors FastAPI {detail} bodies.
 *  Spec S2: `{code, params}` (S1/S5) ride along for dict mapping in mapApiError. */
export class ApiError extends Error {
  detail: string;
  code?: string;
  params?: Record<string, string | number>;

  constructor(detail: string, code?: string, params?: Record<string, string | number>) {
    super(detail);
    this.name = "ApiError";
    this.detail = detail;
    this.code = code;
    this.params = params;
  }
}

interface RequestOptions {
  method?: string;
  /** Plain object → JSON body + Content-Type; FormData → multipart (browser sets boundary). */
  body?: unknown;
}

/** Lane C2 (S5): 403 {code:"email_unverified"} từ BẤT KỲ API call nào →
 *  listener (VerifyGate) mở modal verify. Trả về hàm unsubscribe. */
type UnverifiedListener = () => void;
const unverifiedListeners = new Set<UnverifiedListener>();

export function onEmailUnverified(listener: UnverifiedListener): () => void {
  unverifiedListeners.add(listener);
  return () => {
    unverifiedListeners.delete(listener);
  };
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
    let code: string | undefined;
    let params: Record<string, string | number> | undefined;
    try {
      const data = (await res.json()) as {
        detail?: string | { code?: string; detail?: string };
        code?: string;
        params?: Record<string, string | number>;
      } | null;
      if (data && typeof data.detail === "string") detail = data.detail;
      // Lane M3 P1b: HTTPException detail dict {code, detail} (vd. detached 409).
      if (data && data.detail && typeof data.detail === "object") {
        if (typeof data.detail.detail === "string") detail = data.detail.detail;
        if (typeof data.detail.code === "string") code = data.detail.code;
      }
      if (data && typeof data.code === "string") code = data.code;
      if (data && data.params && typeof data.params === "object") params = data.params;
    } catch {
      // non-JSON error body → keep generic detail
    }
    // R36: non-auth 401 → session lost, bounce to login. Auth endpoints
    // (login/signup/forgot/reset/refresh/logout) handle their own failures.
    if (res.status === 401 && !path.startsWith("/api/auth/")) {
      window.location.assign("/signin");
    }
    // Lane C2 (S5): gating 403 email_unverified → mở verify modal.
    if (res.status === 403 && code === "email_unverified") {
      for (const listener of unverifiedListeners) listener();
    }
    throw new ApiError(detail, code, params);
  }
  // 204 = no body (Plan M PUTs) — res.json() would throw on empty payload.
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** R2 presigned PUT URL: upload thẳng browser → storage, không qua backend. */
export interface PresignResponse {
  storage_key: string;
  url: string;
  max_bytes: number;
}

/** GET /api/quota/me (WS-ADMIN T6): quota hiện tại — null = 401/403 (ẩn widget). */
export interface QuotaMe {
  daily_limit: number;
  daily_used: number;
  weekly_limit: number;
  weekly_used: number;
  daily_remaining: number;
  weekly_remaining: number;
}

/** Lane K (admin): Kaggle GPU/TPU quota — giây; refresh = quotaRefreshTime. */
export interface KaggleQuotaBlock {
  used_s: number;
  total_s: number;
  remaining_s: number;
  refresh: string | null;
}

export interface KaggleQuota {
  gpu: KaggleQuotaBlock;
  tpu: KaggleQuotaBlock;
}

const TYPE_BY_EXT: Record<string, string> = {
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  png: "image/png",
  webp: "image/webp",
  pdf: "application/pdf",
  // Lane B Task 5 (spec #1): ảnh phone — server CONTENT_TYPE_BY_EXT cùng value.
  heic: "image/heic",
  heif: "image/heif",
  avif: "image/avif",
};

/** Content hash cho content-addressed key (uploads/{sha256}.{ext}). */
export async function sha256Hex(blob: Blob): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

/** PUT ArrayBuffer thẳng tới presigned URL qua XMLHttpRequest —
 * upload.onprogress là chỉ có cách report upload progress. KHÔNG set
 * Content-Type: body là ArrayBuffer (không phải Blob) nên browser không
 * tự thêm header → khớp signature đã kí. No credentials: cross-origin
 * presigned endpoint (R2/localstack). */
export function putPresigned(
  url: string,
  data: ArrayBuffer,
  onProgress?: (percent: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress?.(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else reject(new ApiError(`HTTP ${xhr.status}`));
    };
    xhr.onerror = () => reject(new ApiError(translate("errors.uploadFailed")));
    xhr.send(data);
  });
}

/** Presigned upload flow (spec 2026-10-10): presign → PUT ArrayBuffer → storage
 * (progress) → pdf.js đếm trang (image = 1) → POST /api/jobs metadata-only. */
async function uploadPresigned(
  file: File | Blob,
  opts?: {
    filename?: string;
    preprocess?: object;
    output_format?: string;
    mode?: string;
    onProgress?: (percent: number) => void;
    onPhase?: (phase: "uploading" | "counting") => void;
  },
): Promise<{ id: number; status: string }> {
  const blob = file as Blob;
  const filename = opts?.filename ?? (file as File).name;
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  const content_type = TYPE_BY_EXT[ext] || blob.type || "application/octet-stream";
  const sha256 = await sha256Hex(blob);
  const presign = await api.presignUpload({
    filename,
    content_type,
    size_bytes: blob.size,
    sha256,
    output_format: opts?.output_format,
    mode: opts?.mode,
  });
  opts?.onPhase?.("uploading");
  // ArrayBuffer (KHÔNG Blob) — browser không tự thêm Content-Type header.
  await putPresigned(presign.url, await blob.arrayBuffer(), opts?.onProgress);
  opts?.onPhase?.("counting");
  // Page count client-side (spec): pdf.js; image luôn là 1.
  const page_count =
    content_type === "application/pdf" ? (await loadPdf(file as File)).numPages : 1;
  const body: Record<string, unknown> = { storage_key: presign.storage_key, page_count };
  // Spec #3 steer: create body gửi tên file gốc (server lưu cột jobs.filename → search q).
  body.filename = filename;
  if (opts?.preprocess !== undefined) body.preprocess = opts.preprocess;
  if (opts?.output_format !== undefined) body.output_format = opts.output_format;
  if (opts?.mode !== undefined) body.mode = opts.mode;
  return request<{ id: number; status: string }>("/api/jobs", { method: "POST", body });
}

export const api = {
  // S5: register KHÔNG set cookie (duplicate cũng {status:"ok"} — anti-enumeration)
  // → client tự login lấy session (Lane C2 Task 1).
  register: (email: string, password: string) =>
    request<{ status: string }>("/api/auth/register", { method: "POST", body: { email, password } }),
  login: (email: string, password: string) =>
    request<User>("/api/auth/login", { method: "POST", body: { email, password } }),
  logout: () => request<unknown>("/api/auth/logout", { method: "POST" }),
  me: () => request<User>("/api/auth/me"),
  updateProfile: (body: { current_password: string; email?: string; new_password?: string }) =>
    request<User>("/api/auth/profile", { method: "PATCH", body }),
  refresh: () => request<unknown>("/api/auth/refresh", { method: "POST" }),
  // S5: verify mã 6 số / resend — exempt khỏi gating 403 email_unverified.
  verifyCode: (code: string) =>
    request<unknown>("/api/auth/verify", { method: "POST", body: { code } }),
  verifyResend: () => request<unknown>("/api/auth/verify/resend", { method: "POST" }),
  forgotEmail: (email: string) =>
    request<unknown>("/api/auth/password/forgot", { method: "POST", body: { email } }),
  // S5: reset contract {email, code, password} (mã 6 số TTL 5p — không còn token).
  resetPassword: (body: { email: string; code: string; password: string }) =>
    request<unknown>("/api/auth/password/reset", { method: "POST", body }),
  // Phase 4: server-side pagination (page default 1, page_size default 10 max 100).
  // Spec #3: filters q (filename ILIKE) / sort (newest|oldest) / status — server-side.
  listJobs: (page = 1, page_size = 10, filters?: { q?: string; sort?: string; status?: string }) => {
    const q = new URLSearchParams({ page: String(page), page_size: String(page_size) });
    if (filters?.q) q.set("q", filters.q);
    if (filters?.sort) q.set("sort", filters.sort);
    if (filters?.status) q.set("status", filters.status);
    return request<JobsPage>(`/api/jobs?${q.toString()}`);
  },
  getJob: (id: number | string) => request<Job>(`/api/jobs/${id}`),
  // Lane ST: user tự dọn file storage — per-job + batch due (auth, không admin).
  purgeJobStorage: (id: number | string) =>
    request<unknown>(`/api/jobs/${id}/purge-storage`, { method: "POST" }),
  purgeMyStorageDue: () =>
    request<{ purged: number }>("/api/jobs/purge-storage-due", { method: "POST" }),
  // Spec #8: Document IR JSON (404 khi chưa render — UI ẩn nút copy).
  getIr: (id: number | string) => request<Record<string, unknown>>(`/api/jobs/${id}/ir`),
  // R2 presign: sanity-check metadata → presigned PUT URL — browser PUTs
  // ArrayBuffer thẳng vào storage (không chạm backend).
  presignUpload: (body: {
    filename: string;
    content_type: string;
    size_bytes: number;
    sha256: string;
    output_format?: string;
    mode?: string;
  }) => request<PresignResponse>("/api/jobs/presign", { method: "POST", body }),
  uploadJob: (
    file: File | Blob,
    opts?: {
      filename?: string;
      preprocess?: object;
      output_format?: string;
      mode?: string;
      /** 0-100% (XHR upload.onprogress — fetch không report upload progress). */
      onProgress?: (percent: number) => void;
      /** "uploading" = PUT → storage; "counting" = pdf.js đếm trang. */
      onPhase?: (phase: "uploading" | "counting") => void;
    },
  ) => uploadPresigned(file, opts),
  getMyQuota: async (): Promise<QuotaMe | null> => {
    // fetch trực tiếp (request() redirect 401 → /signin): 401/403 = ẩn widget
    const res = await fetch("/api/quota/me", { credentials: "include" });
    if (res.status === 401 || res.status === 403) return null;
    if (!res.ok) throw new ApiError(`HTTP ${res.status}`);
    return (await res.json()) as QuotaMe;
  },
  retryJob: (id: number | string) =>
    request<void>(`/api/jobs/${id}/retry`, { method: "POST" }),
  // Hủy job: queued|extracting|rendering → cancelled (204; terminal 409).
  cancelJob: (id: number | string) =>
    request<void>(`/api/jobs/${id}/cancel`, { method: "POST" }),
  // Spec #1: DELETE → 204 (no body — request() đã xử lý).
  deleteJob: (id: number | string) =>
    request<void>(`/api/jobs/${id}`, { method: "DELETE" }),
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
  // Wave-3 Lane G: layout editor "Lưu layout" → kind md-layout snapshot,
  // KHÔNG đụng text_version (layout artifact = đời sống riêng).
  patchLayoutContent: (id: number | string, markdown: string) =>
    request<{ ok: boolean }>(`/api/jobs/${id}/layout-content`, {
      method: "PATCH",
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
  // WS-ADMIN T5: inline edit 2 limit quota (204 no body)
  adminPatchQuota: (id: number | string, body: QuotaPatch) =>
    request<void>(`/api/admin/users/${id}/quota`, { method: "PATCH", body }),
  adminStats: (from: string, to: string) =>
    request<{ days: AdminStatsDay[] }>(`/api/admin/stats?from=${from}&to=${to}`),
  // Spec #7: worker heartbeats (admin-only) — 403/401 → UI ẩn card.
  getWorkers: () => request<WorkersResponse>("/api/admin/workers"),
  // Lane K: Kaggle GPU/TPU quota (admin-only, 503 khi thiếu package).
  getKaggleQuota: () => request<KaggleQuota>("/api/admin/kaggle-quota"),
  // Lane B3 (S4): storage-cleanup page — stats+old jobs paged, purge-due batch
  adminStorage: (page: number) =>
    request<StorageOverview>(`/api/admin/storage?page=${page}`),
  adminStoragePurgeDue: () =>
    request<{ purged: number }>("/api/admin/storage/purge-due", { method: "POST" }),
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
  // Phase 1 (Sub-system A): text gốc + incremental sync (optimistic lock qua expected_text_version).
  getExtraction: (id: number | string) => request<Extraction>(`/api/jobs/${id}/extraction`),
  saveExtraction: (
    id: number | string,
    body: {
      text: string;
      old_phrase?: string;
      new_phrase?: string;
      expected_text_version: number;
      /** Detached layout 409 → UI confirm → overwrite. */
      force?: boolean;
    },
  ) => request<ExtractionSaveResult>(`/api/jobs/${id}/extraction`, { method: "POST", body }),
  listVersions: (id: number | string, kind?: string) =>
    request<{ items: DocumentVersion[] }>(
      `/api/jobs/${id}/versions${kind ? `?kind=${kind}` : ""}`,
    ),
  // 204 no body — request() đã xử lý.
  restoreVersion: (id: number | string, vid: number) =>
    request<unknown>(`/api/jobs/${id}/versions/${vid}/restore`, { method: "POST" }),
  // Lane B2 (wave-5 S6): feedback — POST auth, content ≤2000; admin list paged.
  submitFeedback: (content: string, page_path?: string) =>
    request<{ id: number }>("/api/feedback", {
      method: "POST",
      body: { content, page_path },
    }),
  adminListFeedbacks: (page = 1, page_size = 20) =>
    request<{ items: FeedbackItem[]; total: number }>(
      `/api/admin/feedbacks?page=${page}&page_size=${page_size}`,
    ),
};
