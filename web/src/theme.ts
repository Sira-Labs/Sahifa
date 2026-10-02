// Light and dark follow the system unless the person picks one with the header toggle; the
// choice sets data-theme on <html> and is remembered in localStorage when storage works.
export type Theme = "light" | "dark";

const KEY = "sahifa-theme";

/** The remembered choice, or null when there is none or storage is unavailable. */
export function storedTheme(): Theme | null {
  try {
    const v = window.localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : null;
  } catch {
    return null;
  }
}

/** The theme in effect: the explicit choice, else the system preference. */
export function currentTheme(): Theme {
  const attr = document.documentElement.dataset.theme;
  if (attr === "light" || attr === "dark") return attr;
  try {
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  } catch {
    return "light";
  }
}

/** Apply a theme and remember it. */
export function setTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  try {
    window.localStorage.setItem(KEY, theme);
  } catch {
    // Private mode or blocked storage: the choice lasts for this page only.
  }
}

/** Apply the remembered choice at start-up (no inline script: the CSP forbids it). */
export function applyStoredTheme(): void {
  const theme = storedTheme();
  if (theme) document.documentElement.dataset.theme = theme;
}
