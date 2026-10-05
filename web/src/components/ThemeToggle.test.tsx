import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it } from "vitest";
import ThemeToggle, { THEME_KEY, initTheme } from "./ThemeToggle";

beforeEach(() => {
  localStorage.removeItem(THEME_KEY);
  document.documentElement.classList.remove("dark");
});

it("initTheme: dark by default on first visit, persists key", () => {
  initTheme();
  expect(document.documentElement).toHaveClass("dark");
  expect(localStorage.getItem(THEME_KEY)).toBe("dark");
});

it("initTheme: respects stored light preference", () => {
  localStorage.setItem(THEME_KEY, "light");
  initTheme();
  expect(document.documentElement).not.toHaveClass("dark");
});

it("btn-theme toggles dark class on <html> and persists", async () => {
  initTheme();
  render(<ThemeToggle />);
  const btn = screen.getByTestId("btn-theme");
  expect(document.documentElement).toHaveClass("dark");
  await userEvent.click(btn);
  expect(document.documentElement).not.toHaveClass("dark");
  expect(localStorage.getItem(THEME_KEY)).toBe("light");
  await userEvent.click(btn);
  expect(document.documentElement).toHaveClass("dark");
  expect(localStorage.getItem(THEME_KEY)).toBe("dark");
});
