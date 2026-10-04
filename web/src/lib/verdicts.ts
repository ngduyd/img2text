/** Spec §7 verdict → Vietnamese UI label. Keys match server RegionOut.verdict. */
export const VERDICT_LABELS: Record<string, string> = {
  ok: "Đã trích xuất",
  image_unextractable: "Hình ảnh chưa trích xuất",
  unreadable: "Không trích xuất được văn bản",
  low_confidence: "Cần kiểm tra",
};
