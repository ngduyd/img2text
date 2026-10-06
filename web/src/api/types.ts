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

export type JobStatus = "queued" | "running" | "done" | "failed";

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
}
