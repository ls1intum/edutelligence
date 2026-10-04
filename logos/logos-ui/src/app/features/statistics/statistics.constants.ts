// Color token definitions for statistics dashboard
// These tokens are defined in src/styles/_tokens.scss

// Diagram/series colors — shades of the active theme's own primary ramp, so
// they follow whichever styles/_tokens-*.scss file is active. Status colors
// (success/warning/error/info) stay fixed across themes; these don't.
export const ICON_COLOR_VARS: string[] = [
  '--color-primary-300',
  '--color-primary-400',
  '--color-primary-500',
  '--color-primary-600',
  '--color-primary-700',
  '--color-primary-800',
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
  return cssVar(ICON_COLOR_VARS[index % 6]);
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
 * Chart role colors for different data series types (theme-reactive; see
 * ICON_COLOR_VARS above).
 */
export const CHART_ROLE = {
  total: cssVar('--color-primary-700'),
  cloud: cssVar('--color-primary-500'),
  local: cssVar('--color-primary-300'),
};
