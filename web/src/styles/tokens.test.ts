import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, it } from "vitest";

/**
 * Contrast gate (plan UI Global Constraints, binding): button label text on
 * --accent must be ≥ 4.5:1 in BOTH themes. Source of truth = tokens.css;
 * values are parsed from the file so this test can't drift from shipped CSS.
 * Path: vitest cwd = web/ (import.meta.url isn't file: under jsdom transform).
 */
const css = readFileSync(resolve(process.cwd(), "src/styles/tokens.css"), "utf8");

/** First --accent hex inside the given selector block. */
function accentIn(selector: string): string {
  const block = css.slice(css.indexOf(selector));
  const end = block.indexOf("}");
  const m = block.slice(0, end).match(/--accent:\s*(#[0-9a-fA-F]{6})/);
  expect(m, `no --accent in ${selector}`).toBeTruthy();
  return m![1];
}

/** WCAG relative luminance of #rrggbb. */
function luminance(hex: string): number {
  const ch = (i: number) => {
    const v = parseInt(hex.slice(1 + i, 3 + i), 16) / 255;
    return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * ch(0) + 0.7152 * ch(2) + 0.0722 * ch(4);
}

/** WCAG contrast ratio of a color against white. */
function contrastOnWhite(hex: string): number {
  return 1.05 / (luminance(hex) + 0.05);
}

it("dark theme --accent vs white ≥ 4.5:1 (primary button labels)", () => {
  expect(contrastOnWhite(accentIn(":root"))).toBeGreaterThanOrEqual(4.5);
});

it("light theme --accent vs white ≥ 4.5:1 (primary button labels)", () => {
  expect(contrastOnWhite(accentIn("html:not(.dark)"))).toBeGreaterThanOrEqual(4.5);
});
