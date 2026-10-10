import { describe, expect, it } from "vitest";
import type { Suggestion } from "../../src/api/types";
import { buildHighlights } from "../../src/lib/highlight";

function sg(over: Partial<Suggestion>): Suggestion {
  return {
    id: 1,
    page_index: 0,
    start: 0,
    end: 0,
    original: "",
    suggestion: "",
    reason: "",
    status: "pending",
    ...over,
  };
}

describe("buildHighlights", () => {
  it("splits text into plain + marked segments around a phrase", () => {
    const segs = buildHighlights("Xin chao ban", [sg({ id: 1, original: "chao", suggestion: "chào" })]);
    expect(segs).toEqual([
      { text: "Xin ", sid: null },
      { text: "chao", sid: 1, occurrence: 0 },
      { text: " ban", sid: null },
    ]);
  });

  it("marks ALL occurrences of a repeated phrase", () => {
    const segs = buildHighlights("loi loi nay", [sg({ id: 2, original: "loi" })]);
    expect(segs.filter((s) => s.sid === 2)).toHaveLength(2);
  });

  it("marks exact code-unit occurrences including inside longer words (server pass-1 semantics)", () => {
    // server locate pass 1 = plain find → "an" trong "ban" match.
    const segs = buildHighlights("ban an", [sg({ id: 3, original: "an" })]);
    expect(segs.map((s) => s.sid)).toEqual([null, 3, null, 3]);
  });

  it("skips pending=false and phrase not found", () => {
    const segs = buildHighlights("khong co", [
      sg({ id: 4, original: "khong co", status: "accepted" }),
      sg({ id: 5, original: "khong ton tai" }),
    ]);
    expect(segs).toEqual([{ text: "khong co", sid: null }]);
  });

  it("resolves overlapping phrases: earlier suggestion wins", () => {
    const segs = buildHighlights("mot hai ba", [
      sg({ id: 6, original: "mot hai" }),
      sg({ id: 7, original: "hai" }),
    ]);
    expect(segs).toEqual([
      { text: "mot hai", sid: 6, occurrence: 0 },
      { text: " ba", sid: null },
    ]);
  });

  it("first occurrence keeps plain testid contract sid, repeats get -{i} suffix", () => {
    const segs = buildHighlights("a a", [sg({ id: 8, original: "a" })]);
    const marks = segs.filter((s) => s.sid !== null);
    expect(marks.map((m) => m.occurrence)).toEqual([0, 1]);
  });
});
