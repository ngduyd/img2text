import { useState } from "react";

export type Theme = "dark" | "light";

export const THEME_KEY = "img2text-theme";

/** Dark is DEFAULT on first visit; stored preference wins once set. main.tsx
 * calls this before render so <html> carries the right class pre-paint. */
export function initTheme(): void {
  const theme: Theme = localStorage.getItem(THEME_KEY) === "light" ? "light" : "dark";
  document.documentElement.classList.toggle("dark", theme === "dark");
  localStorage.setItem(THEME_KEY, theme);
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() =>
    document.documentElement.classList.contains("dark") ? "dark" : "light",
  );

  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    document.documentElement.classList.toggle("dark", next === "dark");
    localStorage.setItem(THEME_KEY, next);
    setTheme(next);
  }

  return (
    <button
      type="button"
      data-testid="btn-theme"
      onClick={toggle}
      aria-label={theme === "dark" ? "Chuyển sang giao diện sáng" : "Chuyển sang giao diện tối"}
      title={theme === "dark" ? "Giao diện tối" : "Giao diện sáng"}
      className="cursor-pointer rounded-lg border border-border px-2 py-1 text-sm text-muted hover:bg-surface"
    >
      <span aria-hidden="true">{theme === "dark" ? "☾" : "☀"}</span>
    </button>
  );
}
