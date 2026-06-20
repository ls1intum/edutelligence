// Colors from src/styles/_tokens.scss
export const AVATAR_COLORS = [
  '#60a5fa',  // --color-avatar-blue
  '#34d399',  // --color-icon-green
  '#fb923c',  // --color-icon-orange
  '#f472b6',  // --color-avatar-pink
  '#a78bfa',  // --color-icon-purple
  '#facc15',  // --color-icon-yellow
] as const;

export function avatarColor(username: string): string {
  let hash = 0;
  for (let i = 0; i < username.length; i++) {
    hash = (hash * 31 + username.charCodeAt(i)) & 0xffff;
  }
  return AVATAR_COLORS[hash % AVATAR_COLORS.length];
}
