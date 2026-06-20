// Color token definitions for statistics dashboard
// These tokens are defined in src/styles/_tokens.scss

export const ICON_COLOR_VARS: string[] = [
  '--color-icon-purple',
  '--color-icon-cyan',
  '--color-icon-green',
  '--color-icon-orange',
  '--color-icon-pink',
  '--color-icon-yellow',
];

/**
 * Converts a CSS custom property token to an rgb(var(...)) string.
 * @param token - The CSS custom property name (e.g., '--color-icon-purple')
 * @returns CSS rgb function with var reference (e.g., 'rgb(var(--color-icon-purple))')
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
    running: '--color-success-500',
    loaded: '--color-icon-cyan',
    sleeping: '--color-icon-purple',
    starting: '--color-warning-500',
    cold: '--color-typography-500',
    stopped: '--color-typography-700',
    error: '--color-error-500',
  };

  const normalizedState = state.toLowerCase();
  const token = stateMap[normalizedState] || stateMap['cold'];
  return cssVar(token);
}

/**
 * Status colors for different result states.
 */
export const STATUS_COLOR: Record<'success' | 'error' | 'timeout' | 'pending', string> = {
  success: cssVar('--color-success-500'),
  error: cssVar('--color-error-500'),
  timeout: cssVar('--color-warning-500'),
  pending: cssVar('--color-icon-purple'),
};

/**
 * Chart role colors for different data series types.
 */
export const CHART_ROLE = {
  total: cssVar('--color-primary-500'),
  cloud: cssVar('--color-icon-cyan'),
  local: cssVar('--color-icon-orange'),
};
