/** Shared API types mirroring server/app (schemas.py, routers). */

export type Verdict = "ok" | "image_unextractable" | "unreadable" | "low_confidence";

export interface User {
  id: number;
  email: string;
  role: string;
  ocr_enabled: boolean;
  /** Present on /api/admin/users items; /api/auth/me (UserOut) omits it. */
  created_at?: string;
}

export interface RegionOut {
  id: string;
  bbox: number[] | null;
  text: string;
  verdict: Verdict;
  placeholder: boolean;
}

export interface ResultPage {
  index: number;
  width: number;
  height: number;
  page_flag: "ok" | "low_confidence" | "unreadable";
  markdown: string;
  regions: RegionOut[];
}

export interface ResultBody {
  model_version: string;
  gpu_seconds: number;
  warnings: string[];
  markdown: string;
  pages: ResultPage[];
  edited_markdown: string | null;
}

/** PATCH /api/jobs/{id}/regions/{rid} response (server contract pinned, Task 2). */
export interface RegionPatchOut {
  id: string;
  text: string;
  markdown_replaced: boolean;
}

export type JobStatus = "queued" | "extracting" | "rendering" | "done" | "failed";

/** Plan M: word style overrides (PUT /layout-style) — server enum-validates keys. */
export interface LayoutStyle {
  fontFamily?: string;
  fontSize?: number;
  align?: "left" | "center" | "justify";
  indent?: number;
  spacing?: string;
  underline?: boolean;
}

/** Plan proofread: gợi ý sửa lỗi OCR (GET /api/jobs/{id}/suggestions). */
export interface Suggestion {
  id: number;
  page_index: number;
  start: number;
  end: number;
  original: string;
  suggestion: string;
  reason: string;
  status: "pending" | "accepted" | "rejected";
}

/** Phase 1 (Sub-system A) API: text gốc + optimistic-lock version. */
export interface Extraction {
  text: string;
  text_version: number;
}

/** POST /extraction response: per-layout sync flags + layouts cần render lại. */
export interface ExtractionSaveResult {
  synced: { md: boolean; docx: boolean };
  needs_render: string[];
  text_version: number;
}

/** GET /versions item (metadata only, newest first). */
export interface DocumentVersion {
  id: number;
  kind: string;
  version: number;
  based_on_text_version: number;
  detached: boolean;
  created_at: string;
}

export interface Job {
  id: number;
  status: JobStatus;
  file_type: string;
  page_count: number;
  error: string | null;
  result: ResultBody | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  /** Plan D4: export format chosen at upload ("md" | "docx"); absent on legacy rows → "md". */
  output_format?: string;
  /** Plan M (M1): exports/{id}/md-layout + docx-layout tồn tại chưa (badge + flow);
   *  Plan M3 (M3-server): + docx_html = exports/{id}/docx.html (word content đã lưu). */
  layout_cache?: { md: boolean; docx: boolean; docx_html?: boolean };
  /** Plan M (M1): word style overrides đã lưu (JSON parsed | null). */
  layout_style?: LayoutStyle | null;
}

/** List endpoint subset: server /api/jobs items omit result; started_at/finished_at
 *  optional — current list serializer omits them (no server change, R52). */
export interface JobListItem {
  id: number;
  status: JobStatus;
  file_type: string;
  page_count: number;
  error: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface AdminStatsDay {
  date: string;
  users_registered: number;
  jobs_submitted: number;
  jobs_done: number;
  jobs_failed: number;
  page_views: number;
  gpu_seconds: number;
  estimated_cost_usd: number;
}

/** Plan S: admin runtime settings — effective value + source (Setting row vs env). */
export type AdminSettingSource = "db" | "env";
export interface AdminSettingEntry {
  value: number | string;
  source: AdminSettingSource;
}
export type AdminSettings = Record<string, AdminSettingEntry>;
export interface AdminSettingsPut {
  scheduler_interval_seconds?: number;
  kaggle_min_queue?: number;
  kaggle_min_gap_seconds?: number;
  llm_base_url?: string;
  llm_model?: string;
  proofread_llm_model?: string;
  llm_api_key?: string;
}
