export const ACCENT_COLORS = ['cyan', 'green', 'orange', 'pink', 'purple', 'yellow'] as const;
export type AccentColor = typeof ACCENT_COLORS[number];

export function avatarColorName(seed: string): AccentColor {
  let hash = 0;
  for (let i = 0; i < seed.length; i++) {
    hash = (hash * 31 + seed.charCodeAt(i)) & 0xffff;
  }
  return ACCENT_COLORS[hash % ACCENT_COLORS.length];
}
