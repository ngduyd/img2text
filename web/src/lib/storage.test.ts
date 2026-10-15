import { test, expect } from "vitest";
import { ageDays, sumKeptBytes } from "./storage";

test("ageDays(null|undefined|'') → 0, không NaN", () => {
  expect(ageDays(null)).toBe(0);
  expect(ageDays(undefined)).toBe(0);
  expect(ageDays("")).toBe(0);
});

test("ageDays floor theo ngày, không âm", () => {
  expect(ageDays(new Date(Date.now() - 8 * 86400000 - 3600000).toISOString())).toBe(8); // 8d+1h → floor 8
  expect(ageDays(new Date(Date.now() - 8 * 86400000 + 3600000).toISOString())).toBe(7); // 8d-1h → floor 7
  expect(ageDays(new Date(Date.now() + 86400000).toISOString())).toBe(0); // future → 0
});

test("sumKeptBytes bỏ null/undefined, sum upload_bytes", () => {
  expect(sumKeptBytes([{ upload_bytes: 1024 }, { upload_bytes: undefined }, {}])).toBe(1024);
  expect(sumKeptBytes([])).toBe(0);
});
