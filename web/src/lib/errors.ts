import { ApiError } from "../api/client";

/** R59: deterministic error→message mapping for every mutation toast + inline error. */
export function mapApiError(e: unknown): string {
  if (e instanceof ApiError) return e.detail;
  if (e instanceof TypeError || String(e).includes("fetch failed"))
    return "Không kết nối được máy chủ. Kiểm tra server đang chạy.";
  return String(e instanceof Error ? e.message : e);
}
