// The appearance: light, dark or as the computer is, which each browser remembers.
export type Theme = "light" | "dark" | "system";

const KEY = "undercover-theme";

export function savedTheme(): Theme {
  try {
    const saved = localStorage.getItem(KEY);
    return saved === "light" || saved === "dark" ? saved : "system";
  } catch {
    return "system";
  }
}

/** Show the page in a theme: data-theme on the page, or none to follow the computer. */
export function showTheme(theme: Theme): void {
  if (theme === "system")
    document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", theme);
}

/** Choose a theme, and remember it in this browser. */
export function chooseTheme(theme: Theme): void {
  showTheme(theme);
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // A browser that keeps nothing still shows the theme until the page reloads.
  }
}
