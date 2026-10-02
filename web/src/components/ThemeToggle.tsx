import { useState } from "react";
import { currentTheme, setTheme, type Theme } from "../theme";

/** Switches between the light and dark theme and remembers the choice. */
export function ThemeToggle() {
  const [theme, setState] = useState<Theme>(() => currentTheme());
  const next: Theme = theme === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      className="icon-btn"
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
      onClick={() => {
        setTheme(next);
        setState(next);
      }}
    >
      {theme === "dark" ? (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
          <circle cx="12" cy="12" r="4.2" />
          <path d="M12 2v2M12 20v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M2 12h2M20 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4" />
        </svg>
      ) : (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5Z" />
        </svg>
      )}
    </button>
  );
}
