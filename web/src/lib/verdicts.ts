/** Spec §7 verdict → UI label i18n key. Keys match server RegionOut.verdict. */
export const VERDICT_KEY: Record<string, string> = {
  ok: "verdict.ok",
  image_unextractable: "verdict.image_unextractable",
  unreadable: "verdict.unreadable",
  low_confidence: "verdict.low_confidence",
};
