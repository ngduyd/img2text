import { describe, expect, it } from "vitest";
import { applyMdOp, type MdHistory } from "../../../src/components/editor/mdFormat";

function H(past: string[] = [], future: string[] = []): MdHistory {
  return { past, future };
}

describe("applyMdOp — wrap ops", () => {
  it("bold wraps selection with **", () => {
    const r = applyMdOp("đẹp quá", 0, 7, "bold");
    expect(r.value).toBe("**đẹp quá**");
    expect(r.start).toBe(2);
    expect(r.end).toBe(9);
  });

  it("bold toggles off markers inside selection", () => {
    const r = applyMdOp("**đẹp**", 0, 7, "bold");
    expect(r.value).toBe("đẹp");
    expect(r.start).toBe(0);
    expect(r.end).toBe(3);
  });

  it("bold toggles off markers hugging the selection", () => {
    const r = applyMdOp("**đẹp**", 2, 5, "bold");
    expect(r.value).toBe("đẹp");
    expect(r.start).toBe(0);
    expect(r.end).toBe(3);
  });

  it("italic wraps with *, strike wraps with ~~", () => {
    expect(applyMdOp("chữ", 0, 3, "italic").value).toBe("*chữ*");
    expect(applyMdOp("chữ", 0, 3, "strike").value).toBe("~~chữ~~");
  });
});

describe("applyMdOp — line ops", () => {
  it("h1/h2/h3 prefix the line at selection", () => {
    expect(applyMdOp("Tiêu đề", 0, 7, "h1").value).toBe("# Tiêu đề");
    expect(applyMdOp("Tiêu đề", 0, 7, "h2").value).toBe("## Tiêu đề");
    expect(applyMdOp("a\nb", 2, 3, "h3").value).toBe("a\n### b");
  });

  it("list prefixes every selected line with -", () => {
    const r = applyMdOp("a\nb", 0, 3, "list");
    expect(r.value).toBe("- a\n- b");
    expect(r.start).toBe(2);
    expect(r.end).toBe(7);
  });

  it("quote prefixes every selected line with >", () => {
    expect(applyMdOp("hello\nworld", 0, 11, "quote").value).toBe("> hello\n> world");
  });

  it("list with selection ending at line start skips the empty next line", () => {
    // "a\nb": chọn "a\n" (end=2) — dòng "b" không bị prefix.
    const r = applyMdOp("a\nb", 0, 2, "list");
    expect(r.value).toBe("- a\nb");
  });
});

describe("applyMdOp — code/link/table", () => {
  it("code fences the selection", () => {
    const r = applyMdOp("x = 1", 0, 5, "code");
    expect(r.value).toBe("```\nx = 1\n```");
    expect(r.start).toBe(4);
    expect(r.end).toBe(9);
  });

  it("link builds [sel](url) from arg", () => {
    const r = applyMdOp("trang", 0, 5, "link", undefined, "https://a.vn");
    expect(r.value).toBe("[trang](https://a.vn)");
  });

  it("table inserts the template at the cursor", () => {
    const r = applyMdOp("ab", 1, 1, "table");
    expect(r.value).toBe("a| Cột 1 | Cột 2 |\n|---|---|\n|  |  |b");
    expect(r.start).toBe(1 + "| Cột 1 | Cột 2 |\n|---|---|\n|  |  |".length);
  });

  it("table accepts custom content via arg", () => {
    const r = applyMdOp("", 0, 0, "table", undefined, "| x |\n|---|");
    expect(r.value).toBe("| x |\n|---|");
  });
});

describe("applyMdOp — undo/redo history (cap 50)", () => {
  it("mutation pushes current value to past and clears future", () => {
    const r = applyMdOp("x", 0, 1, "bold", H([], ["stale"]));
    expect(r.past).toEqual(["x"]);
    expect(r.future).toEqual([]);
    expect(r.value).toBe("**x**");
  });

  it("undo restores previous value and moves current to future", () => {
    const r = applyMdOp("**x**", 0, 4, "undo", H(["x"], []));
    expect(r.value).toBe("x");
    expect(r.past).toEqual([]);
    expect(r.future).toEqual(["**x**"]);
  });

  it("redo re-applies the undone value", () => {
    const r = applyMdOp("x", 0, 1, "redo", H([], ["**x**"]));
    expect(r.value).toBe("**x**");
    expect(r.past).toEqual(["x"]);
    expect(r.future).toEqual([]);
  });

  it("undo with empty past is a no-op; redo with empty future too", () => {
    const r = applyMdOp("giữ", 0, 3, "undo", H());
    expect(r.value).toBe("giữ");
    expect(r.past).toEqual([]);
    const r2 = applyMdOp("giữ", 0, 3, "redo", H());
    expect(r2.value).toBe("giữ");
    expect(r2.future).toEqual([]);
  });

  it("past stack caps at 50 entries", () => {
    const past = Array.from({ length: 50 }, (_, i) => `v${i}`);
    const r = applyMdOp("now", 0, 3, "bold", H(past, []));
    expect(r.past).toHaveLength(50);
    expect(r.past[49]).toBe("now");
    expect(r.past[0]).toBe("v1");
  });
});
