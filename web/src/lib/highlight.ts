import type { Suggestion } from "../api/types";

/**
 * Phase 2 (spec Sub-system B): chia text gốc thành segment thuần + segment
 * highlight theo proofread suggestion. Locate = exact code-unit find (server
 * locate pass 1 — offsets server trả về chỉ informational, client tự locate).
 * Ưu tiên suggestion đứng trước khi 2 phrase chồng nhau; occurrence thứ i của
 * cùng phrase → sid giữ nguyên, mark testid suffixed ngoài UI.
 */
export interface HighlightSegment {
  text: string;
  /** suggestion id bọc segment này; null = text thuần. */
  sid: number | null;
  /** 0-based occurrence index trong số các occurrence của cùng sid. */
  occurrence?: number;
}

export function buildHighlights(text: string, suggestions: Suggestion[]): HighlightSegment[] {
  const ranges: { start: number; end: number; sid: number }[] = [];
  const claimed = (start: number, end: number) =>
    ranges.some((r) => start < r.end && r.start < end);

  for (const s of suggestions) {
    if (s.status !== "pending" || !s.original) continue;
    let from = 0;
    for (;;) {
      const i = text.indexOf(s.original, from);
      if (i < 0) break;
      const end = i + s.original.length;
      if (!claimed(i, end)) ranges.push({ start: i, end, sid: s.id });
      from = i + s.original.length;
    }
  }

  ranges.sort((a, b) => a.start - b.start);

  const segs: HighlightSegment[] = [];
  const cursor = { pos: 0 };
  const occurrenceCount = new Map<number, number>();
  for (const r of ranges) {
    if (r.start > cursor.pos) segs.push({ text: text.slice(cursor.pos, r.start), sid: null });
    const occurrence = occurrenceCount.get(r.sid) ?? 0;
    occurrenceCount.set(r.sid, occurrence + 1);
    segs.push({ text: text.slice(r.start, r.end), sid: r.sid, occurrence });
    cursor.pos = r.end;
  }
  if (cursor.pos < text.length) segs.push({ text: text.slice(cursor.pos), sid: null });
  return segs;
}
