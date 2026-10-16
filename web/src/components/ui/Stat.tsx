/** bytes → "512 B" / "1.5 KB" / "2 MB" (1 chữ số thập phân, bỏ .0). */
export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = n;
  let i = -1;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${Math.round(v * 10) / 10} ${units[i]}`;
}

/** Stat block: big tabular value + optional muted label. valueClassName adds tone
 *  (text-warning/text-success) — Jobs stats render it inside dd (dl>dd kept). */
export function Stat({
  label,
  value,
  testid,
  valueClassName,
}: {
  label?: string;
  value: string;
  testid?: string;
  valueClassName?: string;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span
        data-testid={testid}
        className={`text-lg font-semibold tabular-nums ${valueClassName ?? ""}`}
      >
        {value}
      </span>
      {label !== undefined && <span className="text-xs text-muted">{label}</span>}
    </div>
  );
}
