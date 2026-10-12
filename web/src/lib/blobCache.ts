import { api } from "../api/client";

/**
 * WS-UI: 1 fetch blob gốc cho CẢ 2 section (Văn bản + Layout) — module-level
 * cache theo jobId (Promise share, không fetch đôi). Clear khi job đổi file
 * (retry) → invalidate job không đụng cache này; ponytail: upgrade = TTL.
 */
const cache = new Map<string, Promise<Blob>>();

export function getJobBlob(jobId: string): Promise<Blob> {
  let p = cache.get(jobId);
  if (!p) {
    p = api.downloadJobFile(jobId);
    // Lỗi không cache (retry lần saufetch lại); resolve → giữ vĩnh viễn.
    p.catch(() => cache.delete(jobId));
    cache.set(jobId, p);
  }
  return p;
}

/** Test hook: dọn cache giữa các test (tránh mock khác nhau share entry). */
export function clearJobBlobCache(): void {
  cache.clear();
}
