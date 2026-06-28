// Color token definitions for statistics dashboard
// These tokens are defined in src/styles/_tokens.scss

export const ICON_COLOR_VARS: string[] = [
  '--color-accent-purple',
  '--color-accent-cyan',
  '--color-accent-green',
  '--color-accent-orange',
  '--color-accent-pink',
  '--color-accent-yellow',
];

/**
 * Converts a CSS custom property token to an rgb(var(...)) string.
 * @param token - The CSS custom property name (e.g., '--color-accent-purple')
 * @returns CSS rgb function with var reference (e.g., 'rgb(var(--color-accent-purple))')
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
    sleeping: '--color-accent-purple',
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
  pending: cssVar('--color-accent-purple'),
};

/**
 * Chart role colors for different data series types.
 */
export const CHART_ROLE = {
  total: cssVar('--color-accent-purple'),
  cloud: cssVar('--color-accent-cyan'),
  local: cssVar('--color-accent-orange'),
};
