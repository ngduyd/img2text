/** Shared admin stats date helpers (iso yyyy-mm-dd, inclusive last-7-days). */
export function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

/** Default range: last 7 days (inclusive of today). */
export function last7Days(): { from: string; to: string } {
  const to = new Date();
  const from = new Date(to.getTime() - 6 * 24 * 60 * 60 * 1000);
  return { from: isoDate(from), to: isoDate(to) };
}
