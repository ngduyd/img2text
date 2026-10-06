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

/** First hex of --name inside the given selector block. */
function tokenIn(selector: string, name: string): string {
  const block = css.slice(css.indexOf(selector));
  const end = block.indexOf("}");
  const m = block.slice(0, end).match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`));
  expect(m, `no --${name} in ${selector}`).toBeTruthy();
  return m![1];
}

/** sRGB blend: fg over bg at alpha (8-bit per channel, like browsers). */
function tint(fg: string, bg: string, alpha: number): string {
  const ch = (h: string, i: number) => parseInt(h.slice(1 + i, 3 + i), 16);
  const mix = (i: number) =>
    Math.round(alpha * ch(fg, i) + (1 - alpha) * ch(bg, i));
  return `#${[0, 2, 4].map((i) => mix(i).toString(16).padStart(2, "0")).join("")}`;
}

/** WCAG contrast ratio between two hex colors. */
function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

it("--accent-text ≥ 4.5:1 on bg-accent/10 tint over surface in BOTH themes", () => {
  for (const sel of [":root", "html:not(.dark)"]) {
    const at = tokenIn(sel, "accent-text");
    const bg = tint(tokenIn(sel, "accent"), tokenIn(sel, "surface"), 0.1);
    expect(
      contrast(at, bg),
      `${sel} --accent-text (${at}) on accent/10 tint over surface (${bg})`,
    ).toBeGreaterThanOrEqual(4.5);
  }
});

const indexCss = readFileSync(resolve(process.cwd(), "src/index.css"), "utf8");

it("semantic role tokens present in tokens.css (DESIGN.md §2 map)", () => {
  for (const tok of [
    "--surface-2",
    "--text-muted",
    "--accent-contrast",
    "--radius-sm",
    "--radius-md",
    "--focus-ring",
    "--shadow-card",
  ]) {
    expect(css, `tokens.css missing ${tok}`).toContain(tok);
  }
});

it("skeleton shimmer keyframes + reduced-motion gate exist in index.css", () => {
  expect(indexCss).toContain("@keyframes skeleton");
  expect(indexCss).toContain(".skeleton");
  expect(indexCss).toContain("prefers-reduced-motion");
});
