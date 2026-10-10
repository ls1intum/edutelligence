// Color token definitions for statistics dashboard
// These tokens are defined in src/styles/_tokens.scss

// Diagram/series colors — the categorical chart tokens of the active theme
// (styles/_tokens.scss), eight hues in a fixed order so neighbouring series
// stay distinguishable, also for colour-blind readers. Status colors
// (success/warning/error/info) stay fixed across themes; these don't.
export const ICON_COLOR_VARS: string[] = [
  '--color-series-1',
  '--color-series-2',
  '--color-series-3',
  '--color-series-4',
  '--color-series-5',
  '--color-series-6',
  '--color-series-7',
  '--color-series-8',
];

/**
 * Converts a CSS custom property token to an rgb(var(...)) string.
 * @param token - The CSS custom property name (e.g., '--color-primary-500')
 * @returns CSS rgb function with var reference (e.g., 'rgb(var(--color-primary-500))')
 */
export function cssVar(token: string): string {
  return `rgb(var(${token}))`;
}

/**
 * Returns a color for a series based on index, cycling through available icon colors.
 * @param index - The series index
 * @returns CSS rgb function with color token
 */
export function seriesColor(index: number): string {
  return cssVar(ICON_COLOR_VARS[index % ICON_COLOR_VARS.length]);
}

/**
 * Maps lane state to a color token.
 * @param state - The lane state (case-insensitive)
 * @returns CSS rgb function with the appropriate color token
 */
export function getLaneStateColor(state: string): string {
  const stateMap: Record<string, string> = {
    running: '--color-success',
    loaded: '--color-accent-cyan',
    sleeping: '--color-primary-400',
    starting: '--color-warning',
    cold: '--color-typography-500',
    stopped: '--color-typography-700',
    error: '--color-error',
  };

  const normalizedState = state.toLowerCase();
  const token = stateMap[normalizedState] || stateMap['cold'];
  return cssVar(token);
}

/**
 * Status colors for different result states.
 */
export const STATUS_COLOR: Record<'success' | 'error' | 'timeout' | 'pending', string> = {
  success: cssVar('--color-success'),
  error: cssVar('--color-error'),
  timeout: cssVar('--color-warning'),
  pending: cssVar('--color-primary-500'),
};

/**
 * Chart role colors for different data series types (theme-reactive). A
 * two-part split like local vs. cloud stays in the brand violet, as on the
 * public stats page: a strong step for local, a light one for cloud. Total
 * takes a third step so the KPI cards stay apart; categorical hues are only
 * for charts with more than two series.
 */
export const CHART_ROLE = {
  total: cssVar('--color-primary-800'),
  cloud: cssVar('--color-primary-200'),
  local: cssVar('--color-primary-600'),
};
