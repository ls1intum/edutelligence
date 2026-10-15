/**
 * The message the application server sent with a failed request, if any.
 *
 * The REST APIs report a rejection either as `detail` (the 403/404/409
 * responses the controllers build) or as `error` (the 400 the global exception
 * handler builds), so a caller that wants to show the server's own wording has
 * to accept both. Returns null when the response carries neither, leaving the
 * caller's generic fallback in place.
 */
export function errorDetail(err: unknown): string | null {
  const body = (err as { error?: { detail?: unknown; error?: unknown } } | null)?.error;
  const message = typeof body?.detail === 'string' ? body.detail : body?.error;
  return typeof message === 'string' && message.trim().length > 0 ? message : null;
}
