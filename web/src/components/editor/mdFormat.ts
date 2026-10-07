/**
 * Pure transform cho MD toolbar (job detail mount, JD2 wiring) — không đụng DOM,
 * parent giữ selection + history stacks.
 * ponytail: undo/redo chỉ lưu value string (không lưu selection) — caret về cuối
 * vùng clamp; upgrade = lưu kèm {start,end} khi cần khôi phục selection chính xác.
 */

export type MdFormatOp =
  | "undo"
  | "redo"
  | "h1"
  | "h2"
  | "h3"
  | "bold"
  | "italic"
  | "strike"
  | "list"
  | "quote"
  | "code"
  | "link"
  | "table";

export interface MdHistory {
  past: string[];
  future: string[];
}

export interface MdEditResult {
  value: string;
  start: number;
  end: number;
  past: string[];
  future: string[];
}

const HISTORY_CAP = 50;
const TABLE_TEMPLATE = "| Cột 1 | Cột 2 |\n|---|---|\n|  |  |";

function pushPast(past: string[], value: string): string[] {
  return [...past, value].slice(-HISTORY_CAP);
}

function clamp(n: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, n));
}

/** Wrap/toggle quanh selection: marker đã bọc (trong selection hoặc ngay ngoài) → bỏ. */
function toggleWrap(
  value: string,
  start: number,
  end: number,
  marker: string,
): { value: string; start: number; end: number } {
  const m = marker;
  const sel = value.slice(start, end);
  let next: string;
  let s: number;
  let e: number;
  if (sel.length >= 2 * m.length && sel.startsWith(m) && sel.endsWith(m)) {
    const inner = sel.slice(m.length, -m.length);
    next = value.slice(0, start) + inner + value.slice(end);
    s = start;
    e = start + inner.length;
  } else if (
    start >= m.length &&
    value.slice(start - m.length, start) === m &&
    value.slice(end, end + m.length) === m
  ) {
    next = value.slice(0, start - m.length) + sel + value.slice(end + m.length);
    s = start - m.length;
    e = end - m.length;
  } else {
    next = value.slice(0, start) + m + sel + m + value.slice(end);
    s = start + m.length;
    e = end + m.length;
  }
  return { value: next, start: s, end: e };
}

/** Prefix mỗi dòng trong ròng selection (list `- `, quote `> `). */
function prefixLines(
  value: string,
  start: number,
  end: number,
  prefix: string,
): { value: string; start: number; end: number } {
  const from = value.lastIndexOf("\n", start - 1) + 1;
  // Selection end rơi đúng đầu dòng → dòng đó không thuộc vùng chọn.
  const endAtLineStart = end > start && value.lastIndexOf("\n", end - 1) + 1 === end;
  const to = endAtLineStart
    ? end - 1
    : (() => {
        const i = value.indexOf("\n", end);
        return i === -1 ? value.length : i;
      })();
  const segment = value.slice(from, to);
  const replaced = segment
    .split("\n")
    .map((line) => prefix + line)
    .join("\n");
  const lineCount = segment.split("\n").length;
  const next = value.slice(0, from) + replaced + value.slice(to);
  return {
    value: next,
    start: start + prefix.length,
    end: end + prefix.length * lineCount,
  };
}

/**
 * Áp một lệnh format lên (value, selection). Op biến đổi (bold/italic/…/table)
 * đẩy giá trị hiện tại vào `past` (cap 50) và xoá `future`; undo/redo lùi/chạy
 * qua 2 stack đó. `arg` = URL cho link, hoặc content thay template cho table.
 */
export function applyMdOp(
  value: string,
  start: number,
  end: number,
  op: MdFormatOp,
  history?: MdHistory,
  arg?: string,
): MdEditResult {
  const past = history ? [...history.past] : [];
  const future = history ? [...history.future] : [];
  const base: Omit<MdEditResult, "value" | "start" | "end"> = { past, future };

  if (op === "undo") {
    if (past.length === 0) return { value, start, end, ...base };
    const prev = past[past.length - 1];
    return {
      value: prev,
      start: clamp(start, 0, prev.length),
      end: clamp(end, 0, prev.length),
      past: past.slice(0, -1),
      future: pushPast(future, value),
    };
  }
  if (op === "redo") {
    if (future.length === 0) return { value, start, end, ...base };
    const nxt = future[future.length - 1];
    return {
      value: nxt,
      start: clamp(start, 0, nxt.length),
      end: clamp(end, 0, nxt.length),
      past: pushPast(past, value),
      future: future.slice(0, -1),
    };
  }

  const mutated: Omit<MdEditResult, "value" | "start" | "end"> = {
    past: pushPast(past, value),
    future: [],
  };

  switch (op) {
    case "h1":
    case "h2":
    case "h3": {
      const prefix = `${"#".repeat(Number(op[1]))} `;
      const lineStart = value.lastIndexOf("\n", start - 1) + 1;
      return {
        value: value.slice(0, lineStart) + prefix + value.slice(lineStart),
        start: start + prefix.length,
        end: end + prefix.length,
        ...mutated,
      };
    }
    case "bold": {
      const r = toggleWrap(value, start, end, "**");
      return { ...r, ...mutated };
    }
    case "italic": {
      const r = toggleWrap(value, start, end, "*");
      return { ...r, ...mutated };
    }
    case "strike": {
      const r = toggleWrap(value, start, end, "~~");
      return { ...r, ...mutated };
    }
    case "list": {
      const r = prefixLines(value, start, end, "- ");
      return { ...r, ...mutated };
    }
    case "quote": {
      const r = prefixLines(value, start, end, "> ");
      return { ...r, ...mutated };
    }
    case "code": {
      const before = "```\n";
      const after = "\n```";
      return {
        value: value.slice(0, start) + before + value.slice(start, end) + after + value.slice(end),
        start: start + before.length,
        end: end + before.length,
        ...mutated,
      };
    }
    case "link": {
      const sel = value.slice(start, end);
      const link = `[${sel}](${arg ?? ""})`;
      return {
        value: value.slice(0, start) + link + value.slice(end),
        start: start + link.length,
        end: start + link.length,
        ...mutated,
      };
    }
    case "table": {
      const tpl = arg ?? TABLE_TEMPLATE;
      return {
        value: value.slice(0, start) + tpl + value.slice(end),
        start: start + tpl.length,
        end: start + tpl.length,
        ...mutated,
      };
    }
  }
}
