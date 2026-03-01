/**
 * Native stub — dark mode detection is web-only for Plotly charts.
 * Always returns false on native platforms.
 */
export function useDarkMode(): boolean {
  return false;
}
