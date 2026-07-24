export interface UserNameParts {
  username: string;
  prename?: string | null;
  name?: string | null;
}

/** Full name for display ("Vorname Nachname"), falling back to the username. */
export function userDisplayName(u: UserNameParts): string {
  const full = `${u.prename ?? ''} ${u.name ?? ''}`.trim();
  return full || u.username;
}

/** True when the query matches first name, last name, full name (either order) or username. */
export function userMatchesQuery(u: UserNameParts, query: string): boolean {
  const q = query.toLowerCase().trim();
  if (!q) return true;
  const prename = (u.prename ?? '').toLowerCase();
  const name = (u.name ?? '').toLowerCase();
  return (
    u.username.toLowerCase().includes(q) ||
    `${prename} ${name}`.trim().includes(q) ||
    `${name} ${prename}`.trim().includes(q)
  );
}
