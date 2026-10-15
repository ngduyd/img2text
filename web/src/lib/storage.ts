/** Helper thuần cho trang /storage (Lane RD): tuổi job + tổng bytes còn giữ.
 *  Tách từ Storage.tsx (A10) — không state, không i18n, unit-test trực tiếp. */
import type { JobListItem } from "../api/types";

/** Tuổi job theo ngày (floor, không âm); null/undefined/rỗng → 0 (không NaN). */
export function ageDays(iso: string | null | undefined): number {
  if (!iso) return 0;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return 0;
  return Math.max(0, Math.floor((Date.now() - t) / 86400000));
}

/** Tổng upload_bytes của các job còn giữ (thiếu field → 0). */
export function sumKeptBytes(items: Pick<JobListItem, "upload_bytes">[]): number {
  return items.reduce((sum, j) => sum + (j.upload_bytes || 0), 0);
}
